# SPDX-License-Identifier: MIT
"""The walletd JSON-RPC client against the fake walletd: a token walletd refuses after a restart is replaced
once, and nothing else is retried (a send that may have run is never sent twice)."""
import unittest

import harness  # noqa: F401  (puts server/ on sys.path)
from mutis.fake_chain import FakeChain, fake_keys
from mutis.fake_walletd import FakeWalletd
from mutis.walletd import Walletd, WalletdError


class WalletdClient(unittest.TestCase):
    def setUp(self):
        self.chain = FakeChain()
        self.fake = FakeWalletd(self.chain)
        self.addCleanup(self.fake.server_close)
        self.addCleanup(self.fake.shutdown)
        self.w = Walletd(self.fake.url, timeout=10)

    def calls(self) -> list[str]:
        with self.fake.lock:
            calls, self.fake.calls = self.fake.calls, []
        return calls

    def test_a_token_refused_after_a_restart_is_replaced_once(self):
        """walletd signs tokens with a key it makes at start: the cached token gets 401 until it is replaced."""
        self.assertEqual(self.w.info()["network"], "esmeralda")
        self.assertEqual(self.calls(), ["auth.request", "wallet.get_info"])
        self.fake.restart()
        self.assertEqual(self.w.info()["network"], "esmeralda")
        self.assertEqual(self.calls(), ["wallet.get_info", "auth.request", "wallet.get_info"])
        self.w.info()
        self.assertEqual(self.calls(), ["wallet.get_info"])

    def test_a_refused_send_runs_once(self):
        """walletd refuses an unauthorized call before it runs, so the send made again pays once."""
        self.w.info()
        self.fake.restart()
        tx = self.w.stealth_transfer("sponsor", fake_keys()["address"], 1000, None, 30000)
        self.assertIn(tx, self.chain.receipts)
        self.assertEqual(len(self.chain.transfers), 1)

    def test_other_errors_are_not_retried(self):
        self.w.info()
        self.calls()
        self.fake.fail_next = 1
        with self.assertRaises(WalletdError) as e:
            self.w.info()
        self.assertEqual((e.exception.code, self.calls()), ("walletd_error", ["wallet.get_info"]))

    def test_a_second_refusal_is_an_error(self):
        dispatch = self.fake.dispatch

        def refuse_every_token(method, params):
            result = dispatch(method, params)
            if method == "auth.request":
                self.fake.revoked.add(result["token"])
            return result
        self.fake.dispatch = refuse_every_token
        with self.assertRaises(WalletdError) as e:
            self.w.info()
        self.assertEqual(e.exception.code, "walletd_error")
        self.assertEqual(self.calls(), ["auth.request", "wallet.get_info", "auth.request", "wallet.get_info"])
        self.assertIsNone(self.w._token)


if __name__ == "__main__":
    unittest.main()
