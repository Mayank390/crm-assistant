# Lead Support Agent Testing Plugin

A React application for testing the Lead Support Agent endpoints and WebSocket integration.

## Features

### Left Panel - REST API Plugins
- **Lead Summary** - Get AI-generated comprehensive lead summary
- **AI Insights** - Get structured insights including overview, key insights, engagement score, recommended actions, and risk factors
- **Next Best Steps** - Get AI-recommended prioritized actions
- **Draft Message** - Create personalized email drafts
- **Objection Handling** - Get AI-powered responses to sales objections
- **Meeting Prep** - Generate meeting preparation documents

### Right Panel - WebSocket Chat
- Real-time streaming chat with the Lead Support Agent
- Quick action buttons for common tasks
- Connection status indicator
- Message history with copy-to-clipboard functionality

## Setup

### 1. Install Dependencies

```bash
npm install
```

### 2. Configure Environment

Copy the example environment file and update with your actual IDs:

```bash
cp .env.example .env
```

Edit `.env` and set:

```env
# API Configuration
VITE_API_BASE_URL=http://localhost:8000
VITE_WS_BASE_URL=ws://localhost:8000

# Required IDs for testing
VITE_BUSINESS_ID=your-actual-business-uuid
VITE_LEAD_ID=your-actual-lead-id
VITE_MEMBER_ID=your-actual-member-uuid
```

Alternatively, you can directly edit `src/config.ts`:

```typescript
export const config = {
  api: {
    baseUrl: "http://localhost:8000",
    wsUrl: "ws://localhost:8000",
  },
  businessId: "your-actual-business-uuid",
  leadId: "your-actual-lead-id",
  memberId: "your-actual-member-uuid",
  // ...
};
```

### 3. Start Development Server

```bash
npm run dev
```

The app will be available at `http://localhost:5173` (or another port if 5173 is taken).

### 4. Ensure Backend is Running

Make sure the CRM Assistant API is running on `http://localhost:8000` with the Lead Support Agent endpoints available:

```bash
# From the workspace root
python main.py
```

## API Endpoints Tested

### REST Endpoints (via Left Panel Plugins)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/lead-support/summary` | POST | Get AI summary of a lead |
| `/lead-support/insights` | POST | Get structured AI insights |
| `/lead-support/next-steps` | POST | Get recommended next steps |
| `/lead-support/draft-message` | POST | Draft personalized messages |
| `/lead-support/objection` | POST | Handle sales objections |
| `/lead-support/meeting-prep` | POST | Generate meeting prep docs |

### WebSocket Endpoint (via Right Panel Chat)

| Endpoint | Description |
|----------|-------------|
| `/ws/lead-support` | Real-time streaming chat with Lead Support Agent |

#### WebSocket Message Types

- `handshake` - Initialize session
- `summarize` - Summarize the lead
- `next_steps` - Get next best steps
- `draft_message` - Draft a message
- `objection` - Handle an objection
- `meeting_prep` - Prepare for meeting
- `email` - Compose email
- `query` - General query

## Usage

1. **Configure IDs**: Set your business ID, lead ID, and member ID in the configuration
2. **Test REST APIs**: Use the left panel plugins to test individual REST endpoints
3. **Test WebSocket**: Use the right panel chat for real-time interaction
4. **Quick Actions**: Use the quick action buttons for common tasks

## Tech Stack

- React 18
- TypeScript
- Vite
- Tailwind CSS
- shadcn/ui components
- React Query
- React Router

## Troubleshooting

### "Not Configured" Warning

If you see a configuration warning, make sure you've set valid IDs in your `.env` file or `src/config.ts`. The placeholder values (`YOUR_BUSINESS_ID_HERE`, etc.) need to be replaced with actual IDs from your database.

### WebSocket Connection Issues

1. Check that the backend is running on the correct port
2. Check browser console for connection errors
3. Ensure CORS is configured on the backend to allow WebSocket connections
4. Try the reconnect button in the chat panel

### REST API Errors

1. Check the backend logs for error details
2. Ensure the lead ID exists in the database
3. Verify the business ID matches your data
