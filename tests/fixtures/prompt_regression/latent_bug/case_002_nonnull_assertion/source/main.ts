import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";

// Standard React 18 bootstrapping pattern — getElementById returns
// HTMLElement | null, but we know the element exists in index.html.
const root = ReactDOM.createRoot(
  document.getElementById("root")!
);

root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
