import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { api } from "../api/client";

export default function TransactionHistory() {
  const { user } = useAuth();
  const [transactions, setTransactions] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.listTransactions(user.id)
      .then(setTransactions)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [user.id]);

  return (
    <div className="page transaction-history-page">
      <h2>Transaction History</h2>
      {loading ? (
        <p className="loading-text">Loading...</p>
      ) : transactions.length === 0 ? (
        <div className="empty-state">
          <p>No transactions yet</p>
          <Link to="/send" className="btn btn-primary">Send your first transfer</Link>
        </div>
      ) : (
        <div className="transaction-list full">
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
