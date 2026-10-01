import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { api } from "../api/client";
import { getQueue } from "../services/syncService";

export default function TransactionHistory() {
  const { user } = useAuth();
  const [transactions, setTransactions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [queue, setQueue] = useState([]);

  useEffect(() => {
    api.listTransactions(user.id)
      .then(setTransactions)
      .catch(console.error)
      .finally(() => setLoading(false));
    setQueue(getQueue());
  }, [user.id]);

  const queuedIds = new Set(queue.map((q) => q.id));

  return (
    <div className="page transaction-history-page">
      <h2>Transaction History</h2>
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
              {queue.map((txn) => (
                <div key={txn.id} className="transaction-item queued">
                  <div className="txn-info">
                    <p className="txn-recipient">To: Recipient</p>
                    <p className="txn-date">{new Date(txn._queued_at || txn.created_at).toLocaleDateString()}</p>
                  </div>
                  <div className="txn-amount">
                    <p className="txn-value">{txn.source_currency} {txn.source_amount}</p>
                    <span className="status-badge pending">Queued</span>
                  </div>
                </div>
              ))}
            </>
          )}
          {transactions.map((txn) => (
            <Link to={`/transactions/${txn.id}`} key={txn.id} className="transaction-item">
              <div className="txn-info">
                <p className="txn-recipient">Transaction #{txn.id.slice(0, 8)}</p>
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
  );
}
