import { useState, useEffect, useCallback } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { api } from "../api/client";
import CurrencyCalculator from "../components/CurrencyCalculator";
import BalanceCard from "../components/BalanceCard";
import { useOnlineStatus } from "../hooks/useOnlineStatus";
import { syncQueue, getQueue } from "../services/syncService";

export default function Dashboard() {
  const { user } = useAuth();
  const isOnline = useOnlineStatus();
  const [transactions, setTransactions] = useState([]);
  const [recipients, setRecipients] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const [balances, setBalances] = useState([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [queuedCount, setQueuedCount] = useState(0);

  const loadData = useCallback(async () => {
    try {
      const [txns, recips, notifs, bals] = await Promise.all([
        api.listTransactions(user.id),
        api.listRecipients(user.id),
        api.listNotifications(user.id),
        api.getBalances(user.id),
      ]);
      setTransactions(txns.slice(0, 3));
      setRecipients(recips);
      setNotifications(notifs.filter((n) => !n.read).slice(0, 3));
      setBalances(bals);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [user.id]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Auto-sync when coming back online
  useEffect(() => {
    if (!isOnline) {
      setQueuedCount(getQueue().length);
      return;
    }

    const queue = getQueue();
    if (queue.length === 0) return;

    setSyncing(true);
    syncQueue()
      .then(() => {
        setQueuedCount(0);
        loadData();
      })
      .catch(console.error)
      .finally(() => setSyncing(false));
  }, [isOnline, loadData]);

  const firstName = user?.full_name?.split(" ")[0] || "there";

  return (
    <div className="page dashboard-page">
      <div className="welcome-section">
        <h2>Welcome back, {firstName}</h2>
        <p>What would you like to do today?</p>
      </div>

      <BalanceCard balances={balances} onDeposit={loadData} />

      <CurrencyCalculator />

      <div className="quick-actions">
        <Link to="/send" className="quick-action-card">
          <div className="quick-action-icon green">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="12" y1="1" x2="12" y2="23" />
              <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
            </svg>
          </div>
          <span>Send Money</span>
        </Link>
        <Link to="/recipients/new" className="quick-action-card">
          <div className="quick-action-icon yellow">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
              <circle cx="8.5" cy="7" r="4" />
              <line x1="20" y1="8" x2="20" y2="14" />
              <line x1="23" y1="11" x2="17" y2="11" />
            </svg>
          </div>
          <span>Add Recipient</span>
        </Link>
        <Link to="/transactions" className="quick-action-card">
          <div className="quick-action-icon blue">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="1" y="4" width="22" height="16" rx="2" ry="2" />
              <line x1="1" y1="10" x2="23" y2="10" />
            </svg>
          </div>
          <span>View History</span>
        </Link>
      </div>

      {syncing && (
        <div className="sync-notice">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="spin">
            <polyline points="23 4 23 10 17 10" />
            <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
          </svg>
          <span>Syncing your queued transactions...</span>
        </div>
      )}

      {queuedCount > 0 && !syncing && (
        <div className="queued-notice">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10" />
            <polyline points="12 6 12 12 16 14" />
          </svg>
          <span>{queuedCount} transaction{queuedCount > 1 ? "s" : ""} pending sync</span>
        </div>
      )}

      {notifications.length > 0 && (
        <div className="dashboard-section">
          <div className="section-header">
            <h3>Notifications</h3>
            <Link to="/notifications" className="see-all">See all</Link>
          </div>
          <div className="notification-list">
            {notifications.map((n) => (
              <div key={n.id} className="notification-item unread">
                <div className="notification-dot" />
                <div>
                  <p className="notification-title">{n.title}</p>
                  <p className="notification-message">{n.message}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="dashboard-section">
        <div className="section-header">
          <h3>Recent Transactions</h3>
          <Link to="/transactions" className="see-all">See all</Link>
        </div>
        {loading ? (
          <p className="loading-text">Loading...</p>
        ) : transactions.length === 0 ? (
          <div className="empty-state">
            <p>No transactions yet</p>
            <Link to="/send" className="btn btn-primary">Send your first transfer</Link>
          </div>
        ) : (
          <div className="transaction-list">
            {transactions.map((txn) => (
              <Link to={`/transactions/${txn.id}`} key={txn.id} className="transaction-item">
                <div className="txn-info">
                  <p className="txn-recipient">To: {txn.recipient_id ? "Recipient" : "Unknown"}</p>
                  <p className="txn-date">{new Date(txn.created_at).toLocaleDateString()}</p>
                </div>
                <div className="txn-amount">
                  <p className="txn-value">{txn.source_currency} {txn.source_amount}</p>
                  <span className={`status-badge ${txn.status.toLowerCase()}`}>{txn.status}</span>
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>

      {recipients.length > 0 && (
        <div className="dashboard-section">
          <div className="section-header">
            <h3>Your Recipients</h3>
            <Link to="/recipients" className="see-all">See all</Link>
          </div>
          <div className="recipient-chips">
            {recipients.slice(0, 5).map((r) => (
              <div key={r.id} className="recipient-chip">
                <span className="recipient-avatar">{r.full_name.charAt(0)}</span>
                <span className="recipient-name">{r.full_name}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
