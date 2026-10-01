import { useState, useRef, useEffect } from "react";

const LANGUAGES = [
  { code: "en", name: "English", flag: "🇬🇧" },
  { code: "sn", name: "Shona", flag: "🇿🇼" },
  { code: "nd", name: "Ndebele", flag: "🇿🇦" },
  { code: "ny", name: "Chichewa", flag: "🇲🇼" },
  { code: "pt", name: "Português", flag: "🇲🇿" },
];

export default function LanguageSelector() {
  const [open, setOpen] = useState(false);
  const [current, setCurrent] = useState(
    () => localStorage.getItem("mukuru_lang") || "en"
  );
  const ref = useRef(null);

  useEffect(() => {
    function handleClick(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const select = (code) => {
    setCurrent(code);
    localStorage.setItem("mukuru_lang", code);
    setOpen(false);
  };

  const currentLang = LANGUAGES.find((l) => l.code === current);

  return (
    <div className="lang-selector" ref={ref}>
      <button
        className="lang-toggle"
        onClick={() => setOpen(!open)}
        aria-label="Select language"
      >
        <span className="lang-flag">{currentLang?.flag}</span>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>
      {open && (
        <div className="lang-dropdown">
          {LANGUAGES.map((lang) => (
            <button
              key={lang.code}
              className={`lang-option ${lang.code === current ? "active" : ""}`}
              onClick={() => select(lang.code)}
            >
              <span className="lang-flag">{lang.flag}</span>
              <span>{lang.name}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
