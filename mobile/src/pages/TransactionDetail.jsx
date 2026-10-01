import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "../api/client";

export default function TransactionDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [transaction, setTransaction] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getTransaction(id)
      .then(setTransaction)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) return <div className="page"><p className="loading-text">Loading...</p></div>;
  if (!transaction) return <div className="page"><p>Transaction not found</p></div>;

  return (
    <div className="page transaction-detail-page">
      <button className="back-btn" onClick={() => navigate(-1)}>
        &larr; Back
      </button>
      <h2>Transaction Details</h2>

      <div className="detail-card">
        <div className="detail-row">
          <span>Status</span>
          <span className={`status-badge ${transaction.status.toLowerCase()}`}>{transaction.status}</span>
        </div>
        <div className="detail-row">
          <span>Amount</span>
          <strong>{transaction.source_currency} {transaction.source_amount}</strong>
        </div>
        <div className="detail-row">
          <span>Fee</span>
          <strong>{transaction.source_currency} {transaction.fee_amount}</strong>
        </div>
        <div className="detail-row">
          <span>Total Debit</span>
          <strong>{transaction.source_currency} {transaction.total_debit}</strong>
        </div>
        <div className="detail-row">
          <span>Exchange Rate</span>
          <strong>1 {transaction.source_currency} = {transaction.fx_rate} {transaction.target_currency}</strong>
        </div>
        <div className="detail-row">
          <span>Recipient Gets</span>
          <strong>{transaction.target_currency} {transaction.recipient_amount}</strong>
        </div>
        <div className="detail-row">
          <span>Date</span>
          <strong>{new Date(transaction.created_at).toLocaleString()}</strong>
        </div>
      </div>

      <h3>Tracking</h3>
      <div className="timeline">
        {transaction.events.map((event, i) => (
          <div key={event.id} className="timeline-item">
            <div className="timeline-dot" />
            <div className="timeline-content">
              <p className="timeline-status">{event.status}</p>
              <p className="timeline-note">{event.note}</p>
              <p className="timeline-date">{new Date(event.created_at).toLocaleString()}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
