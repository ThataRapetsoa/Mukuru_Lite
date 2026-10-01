import { useAuth } from "../context/AuthContext";
import { useNavigate } from "react-router-dom";

export default function Profile() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  if (!user) return null;

  return (
    <div className="page profile-page">
      <h2>Profile</h2>
      <div className="profile-card">
        <div className="profile-avatar">{user.full_name.charAt(0)}</div>
        <h3>{user.full_name}</h3>
        <p className="profile-detail">{user.phone_number}</p>
        {user.email && <p className="profile-detail">{user.email}</p>}
        <p className="profile-detail">Member since {new Date(user.created_at).toLocaleDateString()}</p>
      </div>

      <div className="settings-section">
        <h3>Settings</h3>
        <div className="settings-list">
          <div className="settings-item">
            <span>Language</span>
            <span>English</span>
          </div>
          <div className="settings-item">
            <span>Currency</span>
            <span>USD</span>
          </div>
          <div className="settings-item">
            <span>Notifications</span>
            <span>Enabled</span>
          </div>
        </div>
      </div>

      <button className="btn btn-danger btn-large" onClick={handleLogout}>
        Log Out
      </button>
    </div>
  );
}
