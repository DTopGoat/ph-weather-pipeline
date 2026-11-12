// Hourly weather data is published to GitHub Pages, which serves it with CORS enabled.
// The app itself is static and deployed separately, so data updates never redeploy it.
window.PHW_CONFIG = {
  dataBase: (location.hostname === "localhost" || location.hostname === "127.0.0.1")
    ? "./data"
    : "https://dtopgoat.github.io/ph-weather-pipeline/data",
};
