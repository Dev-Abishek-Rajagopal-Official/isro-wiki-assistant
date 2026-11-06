import { StrictMode, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { Provider } from "react-redux";
import { RouterProvider } from "react-router-dom";
import { useAppDispatch } from "./app/hooks";
import { router } from "./app/router";
import { store } from "./app/store";
import { restoreSession } from "./features/auth/authSlice";
import "./index.css";

function App() {
  const dispatch = useAppDispatch();
  useEffect(() => {
    void dispatch(restoreSession());
  }, [dispatch]);
  return <RouterProvider router={router} />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Provider store={store}>
      <App />
    </Provider>
  </StrictMode>,
);
