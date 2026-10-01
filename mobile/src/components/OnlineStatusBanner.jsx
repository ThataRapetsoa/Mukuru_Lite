import { useOnlineStatus } from "../hooks/useOnlineStatus";
import { getQueue } from "../services/syncService";

export default function OnlineStatusBanner() {
  const isOnline = useOnlineStatus();
  const queue = getQueue();

  if (isOnline && queue.length === 0) return null;

  if (!isOnline) {
    return (
      <div className="status-banner offline">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <line x1="1" y1="1" x2="23" y2="23" />
          <path d="M16.72 11.06A10.94 10.94 0 0 1 19 12.55" />
          <path d="M5 12.55a10.94 10.94 0 0 1 5.17-2.39" />
          <path d="M10.71 5.05A16 16 0 0 1 22.58 9" />
          <path d="M1.42 9a15.91 15.91 0 0 1 4.7-2.88" />
          <path d="M8.53 16.11a6 6 0 0 1 6.95 0" />
          <line x1="12" y1="20" x2="12.01" y2="20" />
        </svg>
        <span>
          You're offline. {queue.length > 0
            ? `${queue.length} transaction${queue.length > 1 ? "s" : ""} queued for sync.`
            : "Transactions will be queued."}
        </span>
      </div>
    );
  }

  if (isOnline && queue.length > 0) {
    return (
      <div className="status-banner syncing">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="spin">
          <polyline points="23 4 23 10 17 10" />
          <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
        </svg>
        <span>Syncing {queue.length} transaction{queue.length > 1 ? "s" : ""}...</span>
      </div>
    );
  }

  return null;
}
