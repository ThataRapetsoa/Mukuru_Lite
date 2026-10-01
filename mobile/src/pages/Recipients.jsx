import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { api } from "../api/client";

export default function Recipients() {
  const { user } = useAuth();
  const [recipients, setRecipients] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.listRecipients(user.id)
      .then(setRecipients)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [user.id]);

  return (
    <div className="page recipients-page">
      <div className="page-header">
        <h2>Recipients</h2>
        <Link to="/recipients/new" className="btn btn-primary">Add New</Link>
      </div>
      {loading ? (
        <p className="loading-text">Loading...</p>
      ) : recipients.length === 0 ? (
        <div className="empty-state">
          <p>No recipients yet</p>
          <Link to="/recipients/new" className="btn btn-primary">Add your first recipient</Link>
        </div>
      ) : (
        <div className="recipient-list">
          {recipients.map((r) => (
            <div key={r.id} className="recipient-card">
              <div className="recipient-avatar large">{r.full_name.charAt(0)}</div>
              <div className="recipient-details">
                <p className="recipient-name">{r.full_name}</p>
                <p className="recipient-phone">{r.phone_number}</p>
                <p className="recipient-country">{r.country} &middot; {r.payout_method}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
