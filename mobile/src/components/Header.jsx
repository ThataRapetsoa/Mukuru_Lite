import { useAuth } from "../context/AuthContext";
import { useNavigate } from "react-router-dom";
import LanguageSelector from "./LanguageSelector";

export default function Header() {
  const { user } = useAuth();
  const navigate = useNavigate();

  const firstName = user?.full_name?.split(" ")[0] || "there";

  return (
    <header className="app-header">
      <div className="header-brand">
        <span className="brand-logo">M</span>
        <span className="brand-name">Mukuru</span>
      </div>
      <div className="header-actions">
        <LanguageSelector />
        <span className="header-greeting">Hi, {firstName}</span>
        <button
          className="header-profile-btn"
          onClick={() => navigate("/profile")}
          aria-label="Profile"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
            <circle cx="12" cy="7" r="4" />
          </svg>
        </button>
      </div>
    </header>
  );
}
