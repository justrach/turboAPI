# MLX Chat Frontend

A modern chat interface for MLX models with a beautiful coral red theme, built with Next.js and shadcn/ui.

## Features

- 🎨 Modern UI using shadcn/ui components
- 🌈 Coral red color theme
- 🔄 Model selection from available MLX models
- 📱 Mobile-friendly responsive design
- 🌓 Light/dark mode with system preference detection
- 🔄 Streaming responses for a more dynamic chat experience
- 🛡️ Server-side API calls to avoid CORS issues

## Getting Started

### Prerequisites

- Node.js 18+ and npm/yarn
- MLX Server running (on default port 8000 or configured via .env)

### Installation

1. Clone the repository
2. Install dependencies:
   ```bash
   cd frontend
   npm install
   ```
3. Create a `.env.local` file based on `.env.example`:
   ```bash
   cp .env.example .env.local
   ```
4. Update the `MLX_API_URL` in `.env.local` to point to your running MLX server

### Development

```bash
npm run dev
```

The development server will start on http://localhost:3000

### Production Build

```bash
npm run build
npm start
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| MLX_API_URL | URL of the MLX server | http://localhost:8000 |

## Architecture

- **Next.js App Router**: For routing and server components
- **shadcn/ui**: For UI components with a coral red theme
- **Server-side API Routes**: To proxy requests to the MLX server
- **Streaming SSE**: For real-time streaming of model responses

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
