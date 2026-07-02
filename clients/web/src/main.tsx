import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { SessionProvider } from "@/contexts/SessionContext";
import "./index.css";
import App from "./App";

async function bootstrap() {
  if (import.meta.env.VITE_MOCK_API === "true") {
    const { worker } = await import("./mocks/browser");
    await worker.start({ onUnhandledRequest: "warn" });
  }

  createRoot(document.getElementById("root")!).render(
    <BrowserRouter>
      <SessionProvider>
        <App />
      </SessionProvider>
    </BrowserRouter>,
  );
}

bootstrap();
