// This script runs before React hydration to prevent theme flash
export const themeScript = `
(function() {
  try {
    var theme = JSON.parse(localStorage.getItem('theme-storage') || '{}').state?.theme || 'dark';
    var systemPrefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    var effectiveTheme = theme === 'system' ? (systemPrefersDark ? 'dark' : 'light') : theme;
    
    document.documentElement.classList.remove('light', 'dark');
    document.documentElement.classList.add(effectiveTheme);
    document.documentElement.setAttribute('data-theme', effectiveTheme);
  } catch (e) {
    // Fallback to the default dark theme
    document.documentElement.classList.add('dark');
    document.documentElement.setAttribute('data-theme', 'dark');
  }
})();
`