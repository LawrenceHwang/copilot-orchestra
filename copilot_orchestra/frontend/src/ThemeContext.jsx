import { createContext, useContext, useEffect, useState } from "react";

const Ctx = createContext({ theme: "light", toggle: () => {} });

export function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(
    () => localStorage.getItem("co_theme") || "light"
  );

  useEffect(() => {
    localStorage.setItem("co_theme", theme);
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  const toggle = () => setTheme((t) => (t === "light" ? "dark" : "light"));

  return <Ctx.Provider value={{ theme, toggle }}>{children}</Ctx.Provider>;
}

export const useTheme = () => useContext(Ctx);

/**
 * Pick a class string based on current theme.
 * Usage: const { d } = useTheme();  d("dark-class", "light-class")
 */
export function useThemeClasses() {
  const { theme } = useTheme();
  return {
    theme,
    d: (darkCls, lightCls) => (theme === "dark" ? darkCls : lightCls),
  };
}
