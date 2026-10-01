import { Outlet } from "react-router-dom";
import BottomNav from "./BottomNav";
import Header from "./Header";
import OnlineStatusBanner from "./OnlineStatusBanner";

export default function Layout() {
  return (
    <div className="app-shell">
      <Header />
      <OnlineStatusBanner />
      <main className="app-main">
        <Outlet />
      </main>
      <BottomNav />
    </div>
  );
}
