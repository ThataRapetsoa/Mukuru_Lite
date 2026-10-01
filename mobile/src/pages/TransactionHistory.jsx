import { useState, useEffect, useCallback } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { api } from "../api/client";
import { getQueue } from "../services/syncService";

const STATUS_FILTERS = [
  { value: "ALL", label: "All" },
  { value: "PENDING", label: "Pending" },
  { value: "PROCESSING", label: "Processing" },
  { value: "IN_TRANSIT", label: "In Transit" },
  { value: "READY_FOR_COLLECTION", label: "Ready" },
  { value: "COLLECTED", label: "Collected" },
  { value: "FAILED", label: "Failed" },
  { value: "CANCELLED", label: "Cancelled" },
];

export default function TransactionHistory() {
  const { user } = useAuth();
  const [transactions, setTransactions] = useState([]);
  const [recipients, setRecipients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [queue, setQueue] = useState([]);
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [searchQuery, setSearchQuery] = useState("");

  const loadData = useCallback(async () => {
    try {
      const [txns, recips] = await Promise.all([
        api.listTransactions(user.id),
        api.listRecipients(user.id),
      ]);
      setTransactions(txns);
      setRecipients(recips);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [user.id]);

  useEffect(() => {
    loadData();
    setQueue(getQueue());
  }, [loadData]);

  const recipientMap = new Map(recipients.map((r) => [r.id, r]));

  const filteredTransactions = transactions.filter((txn) => {
    const matchesStatus = statusFilter === "ALL" || txn.status === statusFilter;
    const recipient = recipientMap.get(txn.recipient_id);
    const matchesSearch =
      !searchQuery ||
      recipient?.full_name?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      txn.id.toLowerCase().includes(searchQuery.toLowerCase());
    return matchesStatus && matchesSearch;
  });

  const totalSent = transactions.reduce(
    (sum, txn) => sum + parseFloat(txn.total_debit),
    0
  );

  const queuedRecipients = queue.map((q) => {
    const recipient = recipientMap.get(q.recipient_id);
    return { ...q, recipient_name: recipient?.full_name || "Unknown" };
  });

  return (
    <div className="page transaction-history-page">
      <h2>Transaction History</h2>

      {transactions.length > 0 && (
        <div className="history-summary">
          <div className="summary-item">
            <span className="summary-label">Total Transactions</span>
            <span className="summary-value">{transactions.length}</span>
          </div>
          <div className="summary-item">
            <span className="summary-label">Total Sent</span>
            <span className="summary-value">
              {transactions[0]?.source_currency} {totalSent.toFixed(2)}
            </span>
          </div>
        </div>
      )}

      {transactions.length > 0 && (
        <div className="history-filters">
          <div className="search-box">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input
              type="text"
              placeholder="Search transactions..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>
          <div className="status-filter">
            {STATUS_FILTERS.map((f) => (
              <button
                key={f.value}
                className={`filter-chip ${statusFilter === f.value ? "active" : ""}`}
                onClick={() => setStatusFilter(f.value)}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {loading ? (
        <p className="loading-text">Loading...</p>
      ) : transactions.length === 0 && queue.length === 0 ? (
        <div className="empty-state">
          <p>No transactions yet</p>
          <Link to="/send" className="btn btn-primary">Send your first transfer</Link>
        </div>
      ) : (
        <div className="transaction-list full">
          {queue.length > 0 && (
            <>
              <p className="queue-label">Pending Sync</p>
              {queuedRecipients.map((txn) => (
                <div key={txn.id} className="transaction-item queued">
                  <div className="txn-info">
                    <p className="txn-recipient">{txn.recipient_name}</p>
                    <p className="txn-date">
                      {new Date(txn._queued_at || txn.created_at).toLocaleDateString()}
                    </p>
                  </div>
                  <div className="txn-amount">
                    <p className="txn-value">{txn.source_currency} {txn.source_amount}</p>
                    <span className="status-badge pending">Queued</span>
                  </div>
                </div>
              ))}
            </>
          )}
          {filteredTransactions.length === 0 && searchQuery ? (
            <div className="empty-state">
              <p>No transactions match your search</p>
            </div>
          ) : (
            filteredTransactions.map((txn) => {
              const recipient = recipientMap.get(txn.recipient_id);
              return (
                <Link to={`/transactions/${txn.id}`} key={txn.id} className="transaction-item">
                  <div className="txn-info">
                    <p className="txn-recipient">{recipient?.full_name || "Unknown"}</p>
                    <p className="txn-date">
                      {new Date(txn.created_at).toLocaleDateString()} &middot; {txn.id.slice(0, 8)}
                    </p>
                  </div>
                  <div className="txn-amount">
                    <p className="txn-value">{txn.source_currency} {txn.source_amount}</p>
                    <span className={`status-badge ${txn.status.toLowerCase()}`}>{txn.status}</span>
                  </div>
                </Link>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
