import { Outlet } from "react-router-dom";
import BottomNav from "./BottomNav";
import Header from "./Header";

export default function Layout() {
  return (
    <div className="app-shell">
      <Header />
      <main className="app-main">
        <Outlet />
      </main>
      <BottomNav />
    </div>
  );
}
