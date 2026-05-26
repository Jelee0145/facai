import { createServer } from 'http';
import { parse } from 'url';
import next from 'next';

const dev = process.env.NODE_ENV !== 'production';
const hostname = process.env.HOSTNAME || 'localhost';
const port = parseInt(process.env.PORT || '4524', 10);

// Create Next.js app
const app = next({ dev, hostname, port });
const handle = app.getRequestHandler();

app.prepare().then(() => {
  const server = createServer(async (req, res) => {
    try {
      const parsedUrl = parse(req.url!, true);
      await handle(req, res, parsedUrl);
    } catch (err) {
      console.error('Error occurred handling', req.url, err);
      res.statusCode = 500;
      res.end('Internal server error');
    }
  });
  server.once('error', err => {
    console.error(err);
    process.exit(1);
  });
  server.listen(port, () => {
    console.log(
      `> Server listening at http://${hostname}:${port} as ${
        dev ? 'development' : 'production'
      }`,
    );
  });

  let shuttingDown = false;

  function doShutdown(signal: string) {
    if (shuttingDown) return;
    shuttingDown = true;
    console.log(`\n[SHUTDOWN] Received ${signal}, shutting down...`);
    server.close(() => {
      console.log('[SHUTDOWN] Server closed gracefully');
      process.exit(0);
    });
    setTimeout(() => {
      console.log('[SHUTDOWN] Forcing exit after timeout');
      process.exit(1);
    }, 5000);
  }

  process.on('SIGTERM', () => doShutdown('SIGTERM'));
  process.on('SIGINT', () => doShutdown('SIGINT'));
  process.on('unhandledRejection', (reason) => {
    console.error('[SHUTDOWN] Unhandled rejection:', reason);
  });
});
