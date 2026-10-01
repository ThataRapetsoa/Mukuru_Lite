import { useState, useEffect } from "react";
import { useAuth } from "../context/AuthContext";
import { api } from "../api/client";

export default function Notifications() {
  const { user } = useAuth();
  const [notifications, setNotifications] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.listNotifications(user.id)
      .then(setNotifications)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [user.id]);

  const markRead = async (id) => {
    await api.markNotificationRead(id);
    setNotifications((prev) =>
      prev.map((n) => (n.id === id ? { ...n, read: true } : n))
    );
  };

  return (
    <div className="page notifications-page">
      <h2>Notifications</h2>
      {loading ? (
        <p className="loading-text">Loading...</p>
      ) : notifications.length === 0 ? (
        <div className="empty-state">
          <p>No notifications</p>
        </div>
      ) : (
        <div className="notification-list full">
          {notifications.map((n) => (
            <div
              key={n.id}
              className={`notification-item ${n.read ? "read" : "unread"}`}
              onClick={() => !n.read && markRead(n.id)}
            >
              {!n.read && <div className="notification-dot" />}
              <div>
                <p className="notification-title">{n.title}</p>
                <p className="notification-message">{n.message}</p>
                <p className="notification-date">{new Date(n.created_at).toLocaleDateString()}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
