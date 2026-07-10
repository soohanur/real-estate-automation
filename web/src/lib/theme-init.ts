/**
 * Theme constants + the pre-paint init script.
 *
 * Deliberately has no "use client" directive: the root layout is a server
 * component and needs THEME_INIT_SCRIPT at render time.
 */
export type Theme = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

export const THEME_KEY = "theme";

/** Default when the user has never chosen: follow the OS. (Light theme has
 *  been signed off, so system auto-pick is enabled.) */
export const DEFAULT_THEME: Theme = "system";

/** Runs in <head> before first paint, so the page never flashes the wrong
 *  theme. Dependency-free; must not throw when storage is unavailable. */
export const THEME_INIT_SCRIPT = `(function(){try{
var k=${JSON.stringify(THEME_KEY)},d=${JSON.stringify(DEFAULT_THEME)};
var p=localStorage.getItem(k);if(p!=="light"&&p!=="dark"&&p!=="system")p=d;
var r=p==="system"?(window.matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"):p;
document.documentElement.setAttribute("data-theme",r);
}catch(e){document.documentElement.setAttribute("data-theme",${JSON.stringify(DEFAULT_THEME)});}})();`;
