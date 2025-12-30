# 🎮 OSRS Bingo Board

A real-time bingo board for Old School RuneScape drop tracking with Discord bot integration.

## 🚀 Features

- **Real-time Drop Tracking** - Automatically updates when players get drops
- **Discord Integration** - Connects to Dink drop logger
- **Player View System** - Filter board by player with favorites
- **Drop History** - Complete log of all drops with filtering
- **Analytics Dashboard** - Beautiful charts and statistics
- **Admin Controls** - Manage tiles, overrides, and manual entries
- **OSRS Themed** - Medieval fantasy aesthetic

## 📂 Project Structure

```
osrs-bingo/
├── index.html          # Main HTML structure
├── css/
│   └── style.css       # All styling (OSRS theme)
└── js/
    └── app.js          # Application logic
```

## 🌐 Deployment (GitHub Pages)

1. **Push to GitHub**:
   ```bash
   git add .
   git commit -m "Commit Message"
   git push origin main
   ```

2. **Enable GitHub Pages**:
   - Go to repository Settings
   - Navigate to Pages
   - Source: Deploy from main branch
   - Save

3. **Access your site**:
   - URL: `https://yourusername.github.io/your-repo-name/`

## 🔧 Configuration

### API Endpoint
Update the API URL in `js/app.js`:
```javascript
const API_URL = 'https://your-api-url.onrender.com';
```

### Render Hosting
The rest of the python and api scripts are hosted using Render.
however they can easily be hosted however you like. This is simply the option i took.

### Environment Variables (Backend)
Set these in your Render dashboard:
- `MONGODB_URI` - MongoDB connection string
- `BINGO_ADMIN_PASSWORD` - Admin panel password
- `DROP_API_KEY` - API key for Discord bot
- `DISCORD_BOT_TOKEN` - Discord bot token

## 📊 Features Overview

### Bingo Board
- Customizable grid size (3x3 to 9x9)
- Item images from OSRS Wiki
- Tile completion tracking
- Points and bonuses

### Player View
- Filter by player
- Set favorite player
- Color-coded tiles (green = you, yellow = others)
- Personal leaderboard

### Drop History
- Complete drop log
- Date range filtering
- Player filtering
- Delete history entries (admin)

### Analytics
- Total drops & active players
- Most active day & best month
- Drops per day (30 days)
- Day of week analysis
- Hourly heatmap
- Player activity chart
- Month-over-month trends
- Most dropped items

### Admin Panel
- Edit Mode for tiles
- Manual override (add/remove)
- Manual drop logging
- Board size configuration
- Line bonus configuration
- Export/Import board data

## 🎮 Usage

### For Players
1. Visit the site
2. Select your name from "View as" dropdown
3. Click "⭐ Favorite" to remember your selection
4. Green tiles = you completed
5. Yellow tiles = others completed

### For Admins
1. Click "🔐 Admin Login"
2. Enter admin password
3. Access admin controls:
   - Edit tiles
   - Manual overrides
   - Configure board
   - View analytics

## 🔗 API Integration

The frontend connects to a Flask API backend that:
- Receives drops from Discord bot
- Stores data in MongoDB
- Provides endpoints for history and analytics
- Handles admin authentication

## 📱 Mobile Responsive

- Works on desktop, tablet, and mobile
- Touch-friendly controls
- Responsive charts
- Optimized layouts

## 🎨 OSRS Theme

- Brown/gold medieval color scheme
- Parchment backgrounds
- Gold borders and accents
- Pixelated item icons
- Custom scrollbars

## 🛠️ Development

### Local Testing
Simply open `index.html` in a browser. Update API_URL to point to your local API if needed.

### File Structure
- **index.html** (~500 lines) - Clean HTML markup
- **css/style.css** (~650 lines) - All styles organized by section
- **js/app.js** (~1700 lines) - All JavaScript functionality

### Code Organization
- CSS organized with comments for each section
- JavaScript uses clear function names
- Modal HTML kept in index for easy editing
- External dependencies loaded via CDN (Chart.js)

## 📄 License

This project is open source and available for personal use.

## 🤝 Contributing

Feel free to submit issues, fork the repository, and create pull requests for any improvements.

## ⚔️ Built for OSRS Players

Made with ❤️ for the Old School RuneScape community!