import React from "react";
import ReactDOM from "react-dom/client";
import { CssBaseline, ThemeProvider, createTheme } from "@mui/material";
import App from "./App";
import "./styles.css";

const theme = createTheme({
  palette: {
    mode: "light", primary: { main: "#66513a" }, secondary: { main: "#9a7951" },
    background: { default: "#f4efe6", paper: "#fffdf8" }, error: { main: "#a94f43" },
  },
  shape: { borderRadius: 7 },
  zIndex: { mobileStepper: 1000, fab: 1050, speedDial: 1050, appBar: 1100, drawer: 1200, modal: 1300, snackbar: 1400, tooltip: 1500 },
  typography: { fontFamily: '"Segoe UI", system-ui, sans-serif', h1: { fontFamily: "Georgia, serif" }, h2: { fontFamily: "Georgia, serif" } },
  components: {
    MuiButton: { defaultProps: { size: "small" }, styleOverrides: { root: { textTransform: "none" } } },
    MuiTextField: { defaultProps: { size: "small", variant: "outlined" } },
    MuiTooltip: { defaultProps: { arrow: true, enterDelay: 350 } },
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeProvider theme={theme}><CssBaseline /><App /></ThemeProvider>
  </React.StrictMode>
);
