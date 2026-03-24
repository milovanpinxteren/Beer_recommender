#!/usr/bin/env python3
"""Script to create the Shopify widget HTML file."""

WIDGET_HTML = r'''<!-- Beer Recommendation Widget for House of Beers -->
<!-- Paste this code into a Shopify custom HTML section or page -->

<style>
  .beer-rec-widget {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
    max-width: 1200px;
    margin: 0 auto;
    padding: 20px;
  }
  .beer-rec-widget * { box-sizing: border-box; }
  .beer-rec-header { text-align: center; margin-bottom: 30px; }
  .beer-rec-header h2 { font-size: 28px; margin-bottom: 10px; color: #2c3e50; }
  .beer-rec-header p { color: #666; font-size: 16px; }
  .beer-rec-form { background: #f8f9fa; border-radius: 12px; padding: 25px; margin-bottom: 30px; }
  .beer-rec-form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 20px; }
  .beer-rec-field { display: flex; flex-direction: column; }
  .beer-rec-field label { font-size: 14px; font-weight: 600; color: #444; margin-bottom: 6px; }
  .beer-rec-field input, .beer-rec-field select { padding: 12px 14px; border: 2px solid #e0e0e0; border-radius: 8px; font-size: 15px; transition: border-color 0.2s, box-shadow 0.2s; }
  .beer-rec-field input:focus, .beer-rec-field select:focus { outline: none; border-color: #c9a227; box-shadow: 0 0 0 3px rgba(201, 162, 39, 0.15); }
  .beer-rec-btn { background: linear-gradient(135deg, #c9a227 0%, #a8871e 100%); color: white; border: none; padding: 14px 32px; font-size: 16px; font-weight: 600; border-radius: 8px; cursor: pointer; transition: transform 0.2s, box-shadow 0.2s; width: 100%; }
  .beer-rec-btn:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(201, 162, 39, 0.4); }
  .beer-rec-btn:disabled { background: #ccc; cursor: not-allowed; transform: none; box-shadow: none; }
  .beer-rec-loading { text-align: center; padding: 40px; }
  .beer-rec-spinner { width: 50px; height: 50px; border: 4px solid #f3f3f3; border-top: 4px solid #c9a227; border-radius: 50%; animation: beer-spin 1s linear infinite; margin: 0 auto 20px; }
  @keyframes beer-spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
  .beer-rec-error { background: #fee; border: 1px solid #fcc; color: #c00; padding: 15px 20px; border-radius: 8px; margin-bottom: 20px; }

  /* Profile with radar chart */
  .beer-rec-profile { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border-radius: 12px; padding: 25px; margin-bottom: 30px; }
  .beer-rec-profile h3 { margin: 0 0 20px 0; font-size: 20px; }
  .beer-rec-profile-content { display: flex; flex-wrap: wrap; gap: 30px; align-items: center; }
  .beer-rec-radar-container { flex: 0 0 300px; display: flex; justify-content: center; }
  .beer-rec-radar-canvas { width: 300px; height: 300px; }
  .beer-rec-profile-info { flex: 1; min-width: 250px; }
  .beer-rec-profile-stats { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 20px; }
  .beer-rec-stat { background: rgba(255,255,255,0.15); padding: 12px 16px; border-radius: 8px; min-width: 90px; }
  .beer-rec-stat-value { font-size: 22px; font-weight: bold; }
  .beer-rec-stat-label { font-size: 11px; opacity: 0.9; }
  .beer-rec-profile-category { background: rgba(255,255,255,0.2); padding: 10px 15px; border-radius: 8px; display: inline-block; margin-top: 10px; }
  .beer-rec-profile-category strong { display: block; font-size: 14px; }
  .beer-rec-profile-category span { font-size: 12px; opacity: 0.9; }

  .beer-rec-results h3 { font-size: 22px; margin-bottom: 15px; color: #2c3e50; }

  /* Carousel */
  .beer-rec-carousel-container { position: relative; margin-bottom: 20px; }
  .beer-rec-carousel { display: flex; gap: 15px; overflow-x: auto; scroll-behavior: smooth; padding: 10px 5px 20px 5px; scrollbar-width: thin; scrollbar-color: #c9a227 #f0f0f0; }
  .beer-rec-carousel::-webkit-scrollbar { height: 8px; }
  .beer-rec-carousel::-webkit-scrollbar-track { background: #f0f0f0; border-radius: 4px; }
  .beer-rec-carousel::-webkit-scrollbar-thumb { background: #c9a227; border-radius: 4px; }
  .beer-rec-carousel-btn { position: absolute; top: 50%; transform: translateY(-70%); width: 36px; height: 36px; border-radius: 50%; background: white; border: 2px solid #e0e0e0; cursor: pointer; display: flex; align-items: center; justify-content: center; font-size: 16px; color: #666; z-index: 10; transition: all 0.2s; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
  .beer-rec-carousel-btn:hover { background: #c9a227; border-color: #c9a227; color: white; }
  .beer-rec-carousel-btn.prev { left: -18px; }
  .beer-rec-carousel-btn.next { right: -18px; }

  /* Compact cards */
  .beer-rec-card { flex: 0 0 170px; background: white; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.08); overflow: hidden; transition: transform 0.2s, box-shadow 0.2s; }
  .beer-rec-card:hover { transform: translateY(-4px); box-shadow: 0 6px 20px rgba(0,0,0,0.12); }
  .beer-rec-card-image { width: 100%; height: 110px; object-fit: contain; background: #f8f9fa; padding: 8px; }
  .beer-rec-card-body { padding: 10px; }
  .beer-rec-card-title { font-size: 12px; font-weight: 600; color: #2c3e50; margin: 0 0 4px 0; line-height: 1.3; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; height: 32px; }
  .beer-rec-card-brewery { font-size: 10px; color: #888; margin-bottom: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .beer-rec-card-meta { display: flex; gap: 4px; flex-wrap: wrap; margin-bottom: 6px; }
  .beer-rec-badge { display: inline-flex; align-items: center; background: #f0f0f0; padding: 2px 5px; border-radius: 10px; font-size: 9px; color: #555; }
  .beer-rec-badge-rating { background: #fff3cd; color: #856404; }
  .beer-rec-card-footer { display: flex; justify-content: space-between; align-items: center; gap: 6px; }
  .beer-rec-price { font-size: 14px; font-weight: bold; color: #2c3e50; }
  .beer-rec-add-btn { background: #c9a227; color: white; border: none; padding: 6px 10px; border-radius: 4px; font-size: 10px; font-weight: 600; cursor: pointer; transition: background 0.2s; white-space: nowrap; }
  .beer-rec-add-btn:hover { background: #a8871e; }
  .beer-rec-add-btn:disabled { background: #ccc; cursor: not-allowed; }
  .beer-rec-add-btn.added { background: #28a745; }

  .beer-rec-tried { border: 2px solid #17a2b8; }
  .beer-rec-tried-badge { background: #17a2b8; color: white; padding: 3px 6px; font-size: 9px; font-weight: 600; text-align: center; }

  .beer-rec-section { margin-top: 30px; }
  .beer-rec-section h4 { font-size: 18px; color: #666; margin-bottom: 15px; padding-bottom: 10px; border-bottom: 2px solid #eee; }

  .beer-rec-confidence-high { border-left: 3px solid #28a745; }
  .beer-rec-confidence-medium { border-left: 3px solid #ffc107; }
  .beer-rec-confidence-low { border-left: 3px solid #6c757d; }

  .beer-rec-toast { position: fixed; bottom: 20px; right: 20px; background: #333; color: white; padding: 12px 20px; border-radius: 8px; z-index: 1000; opacity: 0; transition: opacity 0.3s; }
  .beer-rec-toast.show { opacity: 1; }

  @media (max-width: 768px) {
    .beer-rec-widget { padding: 15px; }
    .beer-rec-form-grid { grid-template-columns: 1fr; }
    .beer-rec-profile-content { flex-direction: column; }
    .beer-rec-radar-container { flex: 0 0 auto; }
    .beer-rec-carousel-btn { display: none; }
    .beer-rec-card { flex: 0 0 150px; }
  }
</style>

<div class="beer-rec-widget" id="beerRecWidget">
  <div class="beer-rec-header">
    <h2>Personalized Beer Recommendations</h2>
    <p>Enter your Untappd username and we'll find beers you'll love based on your taste profile</p>
  </div>

  <div class="beer-rec-form">
    <div class="beer-rec-form-grid">
      <div class="beer-rec-field">
        <label for="untappdUsername">Untappd Username</label>
        <input type="text" id="untappdUsername" placeholder="e.g., craftbeerlover" />
      </div>
      <div class="beer-rec-field">
        <label for="maxPrice">Max Price</label>
        <input type="number" id="maxPrice" placeholder="No limit" min="0" step="0.50" />
      </div>
      <div class="beer-rec-field">
        <label for="numRecs">Number of Recommendations</label>
        <select id="numRecs">
          <option value="5">5 beers</option>
          <option value="10" selected>10 beers</option>
          <option value="15">15 beers</option>
          <option value="20">20 beers</option>
        </select>
      </div>
      <div class="beer-rec-field">
        <label for="styleFilter">Style (optional)</label>
        <select id="styleFilter">
          <option value="">All styles</option>
        </select>
      </div>
    </div>
    <button class="beer-rec-btn" id="getRecsBtn" onclick="beerRec.getRecommendations()">Get My Recommendations</button>
  </div>

  <div id="beerRecLoading" class="beer-rec-loading" style="display: none;">
    <div class="beer-rec-spinner"></div>
    <p>Analyzing your taste profile...</p>
    <p style="font-size: 14px; color: #888;">This may take a moment for new users</p>
  </div>

  <div id="beerRecError" class="beer-rec-error" style="display: none;"></div>
  <div id="beerRecResults" style="display: none;"></div>
  <div id="beerRecToast" class="beer-rec-toast"></div>
</div>

<script>
var beerRec = (function() {
  var API_BASE = "https://recommendation.houseofbeers.nl/api";
  var currentUsername = "";

  // Load styles on page load
  loadStyles();

  function loadStyles() {
    fetch(API_BASE + "/styles/")
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var select = document.getElementById("styleFilter");
        data.styles.forEach(function(style) {
          var option = document.createElement("option");
          option.value = style.category;
          option.textContent = style.category + " (" + style.count + ")";
          select.appendChild(option);
        });
      })
      .catch(function(e) { console.log("Could not load styles:", e); });
  }

  function getRecommendations() {
    var username = document.getElementById("untappdUsername").value.trim();
    var maxPrice = document.getElementById("maxPrice").value;
    var numRecs = document.getElementById("numRecs").value;
    var styleFilter = document.getElementById("styleFilter").value;

    if (!username) { showError("Please enter your Untappd username"); return; }

    currentUsername = username;
    showLoading(true, "Submitting request...");
    hideError();
    document.getElementById("beerRecResults").style.display = "none";

    var body = { username: username, limit: parseInt(numRecs) };
    if (maxPrice) body.price_max = parseFloat(maxPrice);
    if (styleFilter) body.style_filter = styleFilter;

    fetch(API_BASE + "/recommendations/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    })
    .then(function(response) {
      return response.json().then(function(data) { return { ok: response.ok, data: data }; });
    })
    .then(function(result) {
      var data = result.data;
      if (data.status === "pending" && data.task_id) {
        showLoading(true, "Fetching your Untappd profile... This may take up to a minute.");
        pollForResult(data.task_id);
      } else if (result.ok) {
        fetchProfileAndDisplay(data);
      } else {
        throw new Error(data.detail || data.error || "Failed to get recommendations");
      }
    })
    .catch(function(error) { showError(error.message); showLoading(false); });
  }

  function pollForResult(taskId) {
    var maxAttempts = 60, attempts = 0;
    function poll() {
      if (attempts >= maxAttempts) { showError("Request timed out. Please try again."); showLoading(false); return; }
      setTimeout(function() {
        attempts++;
        fetch(API_BASE + "/tasks/" + taskId + "/")
          .then(function(r) { return r.json(); })
          .then(function(data) {
            if (data.status === "completed") { fetchProfileAndDisplay(data.result); }
            else if (data.status === "failed") { showError(data.error || "Failed to generate recommendations"); showLoading(false); }
            else { showLoading(true, "Analyzing your taste profile..."); poll(); }
          })
          .catch(function(error) { showError(error.message); showLoading(false); });
      }, 2000);
    }
    poll();
  }

  function fetchProfileAndDisplay(recData) {
    // Fetch detailed profile for radar chart
    fetch(API_BASE + "/profile/" + currentUsername + "/")
      .then(function(r) { return r.json(); })
      .then(function(profileData) {
        displayResults(recData, profileData);
        showLoading(false);
      })
      .catch(function(e) {
        // Fall back to displaying without detailed profile
        displayResults(recData, null);
        showLoading(false);
      });
  }

  function drawRadarChart(canvasId, profileData) {
    var canvas = document.getElementById(canvasId);
    if (!canvas || !profileData || !profileData.radar_chart) return;

    var ctx = canvas.getContext("2d");
    var width = canvas.width, height = canvas.height;
    var centerX = width / 2, centerY = height / 2;
    var radius = Math.min(width, height) / 2 - 50;

    var axes = profileData.radar_chart.axes || [];
    var values = profileData.radar_chart.values || [];

    if (axes.length < 3) {
      ctx.fillStyle = "rgba(255,255,255,0.8)";
      ctx.font = "14px sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("Not enough data for radar chart", centerX, centerY);
      return;
    }

    var numPoints = axes.length;
    var angleStep = (2 * Math.PI) / numPoints;

    ctx.clearRect(0, 0, width, height);

    // Draw grid circles
    ctx.strokeStyle = "rgba(255,255,255,0.2)";
    ctx.lineWidth = 1;
    for (var level = 1; level <= 4; level++) {
      var levelRadius = (radius * level) / 4;
      ctx.beginPath();
      for (var i = 0; i <= numPoints; i++) {
        var angle = (i % numPoints) * angleStep - Math.PI / 2;
        var x = centerX + levelRadius * Math.cos(angle);
        var y = centerY + levelRadius * Math.sin(angle);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.stroke();
    }

    // Draw axis lines
    ctx.strokeStyle = "rgba(255,255,255,0.3)";
    for (var i = 0; i < numPoints; i++) {
      var angle = i * angleStep - Math.PI / 2;
      ctx.beginPath();
      ctx.moveTo(centerX, centerY);
      ctx.lineTo(centerX + radius * Math.cos(angle), centerY + radius * Math.sin(angle));
      ctx.stroke();
    }

    // Draw data polygon
    ctx.beginPath();
    ctx.fillStyle = "rgba(201, 162, 39, 0.35)";
    ctx.strokeStyle = "rgba(201, 162, 39, 1)";
    ctx.lineWidth = 2;

    for (var i = 0; i <= numPoints; i++) {
      var idx = i % numPoints;
      var angle = idx * angleStep - Math.PI / 2;
      var value = (values[idx] || 0) / 100; // Normalize 0-100 to 0-1
      var x = centerX + radius * value * Math.cos(angle);
      var y = centerY + radius * value * Math.sin(angle);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.fill();
    ctx.stroke();

    // Draw data points
    ctx.fillStyle = "#c9a227";
    for (var i = 0; i < numPoints; i++) {
      var angle = i * angleStep - Math.PI / 2;
      var value = (values[i] || 0) / 100;
      var x = centerX + radius * value * Math.cos(angle);
      var y = centerY + radius * value * Math.sin(angle);
      ctx.beginPath();
      ctx.arc(x, y, 4, 0, 2 * Math.PI);
      ctx.fill();
    }

    // Draw labels
    ctx.fillStyle = "rgba(255,255,255,0.95)";
    ctx.font = "bold 10px sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";

    for (var i = 0; i < numPoints; i++) {
      var angle = i * angleStep - Math.PI / 2;
      var labelRadius = radius + 30;
      var x = centerX + labelRadius * Math.cos(angle);
      var y = centerY + labelRadius * Math.sin(angle);
      var label = axes[i] || "";
      if (label.length > 10) label = label.substring(0, 8) + "..";
      ctx.fillText(label, x, y);
    }
  }

  function displayResults(recData, profileData) {
    var container = document.getElementById("beerRecResults");
    var canvasId = "tasteRadarChart";

    // Use profile data if available, otherwise fall back to recData
    var totalCheckins = profileData ? profileData.total_checkins : (recData.profile_summary.total_checkins || 0);
    var uniqueBeers = profileData ? profileData.unique_beers : (recData.profile_summary.unique_beers || 0);
    var avgRating = profileData ? profileData.rating_profile.average : recData.profile_summary.avg_rating;
    var abvRange = profileData ? profileData.abv_profile.range_label : recData.profile_summary.abv_range;
    var abvCategory = profileData ? profileData.abv_profile.category : "";
    var ratingCategory = profileData ? profileData.rating_profile.category : "";

    var html = '<div class="beer-rec-profile"><h3>Your Taste Profile</h3><div class="beer-rec-profile-content">';
    html += '<div class="beer-rec-radar-container"><canvas id="' + canvasId + '" class="beer-rec-radar-canvas" width="300" height="300"></canvas></div>';
    html += '<div class="beer-rec-profile-info"><div class="beer-rec-profile-stats">';
    html += '<div class="beer-rec-stat"><div class="beer-rec-stat-value">' + totalCheckins + '</div><div class="beer-rec-stat-label">Check-ins</div></div>';
    html += '<div class="beer-rec-stat"><div class="beer-rec-stat-value">' + uniqueBeers + '</div><div class="beer-rec-stat-label">Unique Beers</div></div>';
    html += '<div class="beer-rec-stat"><div class="beer-rec-stat-value">' + parseFloat(avgRating).toFixed(1) + '</div><div class="beer-rec-stat-label">Avg Rating</div></div>';
    html += '<div class="beer-rec-stat"><div class="beer-rec-stat-value">' + abvRange + '</div><div class="beer-rec-stat-label">ABV Range</div></div>';
    html += '</div>';
    if (abvCategory) {
      html += '<div class="beer-rec-profile-category"><strong>' + abvCategory + '</strong><span>' + ratingCategory + '</span></div>';
    }
    html += '</div></div></div>';

    if (recData.recommendations && recData.recommendations.length > 0) {
      html += '<div class="beer-rec-results"><h3>Recommended For You</h3>';
      html += '<div class="beer-rec-carousel-container">';
      html += '<button class="beer-rec-carousel-btn prev" onclick="beerRec.scroll(\'recsCarousel\',-1)">&lt;</button>';
      html += '<div class="beer-rec-carousel" id="recsCarousel">';
      recData.recommendations.forEach(function(rec) { html += renderBeerCard(rec); });
      html += '</div><button class="beer-rec-carousel-btn next" onclick="beerRec.scroll(\'recsCarousel\',1)">&gt;</button></div></div>';
    }

    if (recData.discovery_picks && recData.discovery_picks.length > 0) {
      html += '<div class="beer-rec-section"><h4>Discovery Picks - Try Something New</h4>';
      html += '<div class="beer-rec-carousel-container">';
      html += '<button class="beer-rec-carousel-btn prev" onclick="beerRec.scroll(\'discoveryCarousel\',-1)">&lt;</button>';
      html += '<div class="beer-rec-carousel" id="discoveryCarousel">';
      recData.discovery_picks.forEach(function(rec) { html += renderBeerCard(rec); });
      html += '</div><button class="beer-rec-carousel-btn next" onclick="beerRec.scroll(\'discoveryCarousel\',1)">&gt;</button></div></div>';
    }

    if (recData.tried_beers && recData.tried_beers.length > 0) {
      html += '<div class="beer-rec-section"><h4>Beers You\'ve Tried (In Stock)</h4>';
      html += '<div class="beer-rec-carousel-container">';
      html += '<button class="beer-rec-carousel-btn prev" onclick="beerRec.scroll(\'triedCarousel\',-1)">&lt;</button>';
      html += '<div class="beer-rec-carousel" id="triedCarousel">';
      recData.tried_beers.forEach(function(rec) { html += renderBeerCard(rec, true); });
      html += '</div><button class="beer-rec-carousel-btn next" onclick="beerRec.scroll(\'triedCarousel\',1)">&gt;</button></div></div>';
    }

    container.innerHTML = html;
    container.style.display = "block";

    setTimeout(function() { drawRadarChart(canvasId, profileData); }, 50);
    container.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function renderBeerCard(rec, isTried) {
    var beer = rec.beer;
    var confidenceClass = "beer-rec-confidence-" + rec.confidence;
    var triedClass = (isTried || rec.is_tried) ? "beer-rec-tried" : "";
    var imageUrl = beer.image_url || "https://via.placeholder.com/150x150?text=No+Image";
    var variantId = beer.variant_id || "";

    var html = '<div class="beer-rec-card ' + confidenceClass + ' ' + triedClass + '">';
    if (rec.is_tried) html += '<div class="beer-rec-tried-badge">You\'ve tried this!</div>';
    html += '<img src="' + imageUrl + '" alt="' + beer.title + '" class="beer-rec-card-image" loading="lazy" />';
    html += '<div class="beer-rec-card-body">';
    html += '<h4 class="beer-rec-card-title">' + beer.title + '</h4>';
    html += '<div class="beer-rec-card-brewery">' + beer.vendor + '</div>';
    html += '<div class="beer-rec-card-meta">';
    if (beer.untappd_rating) html += '<span class="beer-rec-badge beer-rec-badge-rating">★' + parseFloat(beer.untappd_rating).toFixed(1) + '</span>';
    if (beer.abv) html += '<span class="beer-rec-badge">' + beer.abv + '%</span>';
    html += '</div>';
    html += '<div class="beer-rec-card-footer">';
    html += '<span class="beer-rec-price">' + (beer.price ? '€' + parseFloat(beer.price).toFixed(2) : '') + '</span>';
    if (variantId) {
      html += '<button class="beer-rec-add-btn" onclick="beerRec.addToCart(\'' + variantId + '\', this)">Add to Cart</button>';
    } else {
      html += '<a href="' + (beer.product_url || 'https://houseofbeers.nl/products/' + beer.handle) + '" class="beer-rec-add-btn" target="_blank">View</a>';
    }
    html += '</div></div></div>';
    return html;
  }

  function scrollCarousel(carouselId, direction) {
    var carousel = document.getElementById(carouselId);
    if (carousel) { carousel.scrollBy({ left: 190 * direction, behavior: "smooth" }); }
  }

  function addToCart(variantId, btn) {
    if (!variantId) return;
    btn.disabled = true;
    btn.textContent = "Adding...";

    fetch("/cart/add.js", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: variantId, quantity: 1 })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      btn.textContent = "Added!";
      btn.classList.add("added");
      showToast("Added to cart: " + data.title);
      setTimeout(function() { btn.textContent = "Add to Cart"; btn.classList.remove("added"); btn.disabled = false; }, 2000);
    })
    .catch(function(e) {
      btn.textContent = "Error";
      setTimeout(function() { btn.textContent = "Add to Cart"; btn.disabled = false; }, 2000);
    });
  }

  function showToast(message) {
    var toast = document.getElementById("beerRecToast");
    toast.textContent = message;
    toast.classList.add("show");
    setTimeout(function() { toast.classList.remove("show"); }, 3000);
  }

  function showLoading(show, message) {
    var loadingDiv = document.getElementById("beerRecLoading");
    loadingDiv.style.display = show ? "block" : "none";
    document.getElementById("getRecsBtn").disabled = show;
    if (message) { var msgP = loadingDiv.querySelector("p"); if (msgP) msgP.textContent = message; }
  }

  function showError(message) {
    var errorDiv = document.getElementById("beerRecError");
    errorDiv.textContent = message;
    errorDiv.style.display = "block";
  }

  function hideError() { document.getElementById("beerRecError").style.display = "none"; }

  return {
    getRecommendations: getRecommendations,
    scroll: scrollCarousel,
    addToCart: addToCart
  };
})();
</script>
'''

if __name__ == "__main__":
    with open("shopify_widget.html", "w", encoding="utf-8") as f:
        f.write(WIDGET_HTML)
    print("Widget saved to shopify_widget.html")
