import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useAuth } from "../auth/AuthContext.jsx";
import { fetchWallet, spendWalletCoins } from "../api/walletApi.js";

const WalletContext = createContext(null);

export function WalletProvider({ children }) {
  const { user } = useAuth();
  const email = user?.email ?? "";

  const [balance, setBalance] = useState(0);
  const [transactions, setTransactions] = useState([]);

  const sync = useCallback(async () => {
    if (!email) {
      setBalance(0);
      setTransactions([]);
      return;
    }
    const w = await fetchWallet();
    setBalance(w.balance);
    setTransactions(w.transactions);
  }, [email]);

  useEffect(() => {
    let active = true;
    sync().catch(() => {
      if (!active) return;
      setBalance(0);
      setTransactions([]);
    });
    return () => {
      active = false;
    };
  }, [sync]);

  const spendCoins = useCallback(
    async (coins, label) => {
      if (!email) return { ok: false };
      try {
        const res = await spendWalletCoins({ amount: coins, note: label });
        if (res.wallet) {
          setBalance(res.wallet.balance);
          setTransactions(res.wallet.transactions);
        }
        return res;
      } catch (err) {
        return { ok: false, error: err instanceof Error ? err.message : "Could not deduct coins." };
      }
    },
    [email],
  );

  const afford = useCallback((coins) => Number(balance) >= Number(coins || 0), [balance]);

  const value = useMemo(
    () => ({
      balance,
      transactions,
      refreshWallet: sync,
      spendCoins,
      canAfford: afford,
    }),
    [balance, transactions, sync, spendCoins, afford],
  );

  return <WalletContext.Provider value={value}>{children}</WalletContext.Provider>;
}

export function useWallet() {
  const ctx = useContext(WalletContext);
  if (!ctx) {
    throw new Error("useWallet must be used within WalletProvider");
  }
  return ctx;
}
