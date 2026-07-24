import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import Admin from "./Admin.jsx";
import "./index.css";

const Root = window.location.hash === "#admin" ? Admin : App;
createRoot(document.getElementById("root")).render(<Root />);
