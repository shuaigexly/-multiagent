import { createRoot } from "react-dom/client";
import App from "./App.tsx";
import "./index.css";

const sentryDsn = import.meta.env.VITE_SENTRY_DSN;

if (sentryDsn) {
  const sentryModule = "@sentry/react";
  import(sentryModule)
    .then((Sentry) => {
      Sentry.init({ dsn: sentryDsn, tracesSampleRate: 0.1 });
    })
    .catch(() => {
      /* sentry not installed */
    });
}

createRoot(document.getElementById("root")!).render(<App />);
