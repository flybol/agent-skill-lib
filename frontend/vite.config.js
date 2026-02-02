import { defineConfig } from "vite";

// 自定义插件：为 preview 模式添加代理功能
function proxyPlugin() {
    return {
        name: 'proxy-preview',
        configurePreviewServer(server) {
            const http = require('http');

            server.middlewares.use((req, res, next) => {
                // 代理 /api/、/ws/、/frames/ 请求到后端
                const path = req.url || '';
                if (path.startsWith('/api/') || path.startsWith('/ws/') || path.startsWith('/frames/')) {
                    const options = {
                        hostname: 'localhost',
                        port: 8000,
                        path: path,
                        method: req.method,
                        headers: {
                            ...req.headers,
                            host: 'localhost:8000',
                        },
                    };

                    // WebSocket 升级需要特殊处理，这里简化处理
                    if (path.startsWith('/ws/')) {
                        res.writeHead(426, { 'Content-Type': 'text/plain' });
                        res.end('WebSocket 需要直接连接后端');
                        return;
                    }

                    // HTTP 请求代理
                    const proxyReq = http.request(options, (proxyRes) => {
                        // 过滤掉可能干扰的响应头
                        const headers = { ...proxyRes.headers };
                        delete headers['content-length'];
                        res.writeHead(proxyRes.statusCode, headers);
                        proxyRes.pipe(res);
                    });

                    proxyReq.on('error', (err) => {
                        console.error('代理请求失败:', err.message);
                        if (!res.headersSent) {
                            res.writeHead(500, { 'Content-Type': 'application/json' });
                            res.end(JSON.stringify({ error: '后端服务连接失败' }));
                        }
                    });

                    req.pipe(proxyReq);
                } else {
                    next();
                }
            });
        },
    };
}

export default defineConfig({
    plugins: [proxyPlugin()],
    server: {
        host: "0.0.0.0",
        port: 5173,
        strictPort: true,
        open: true,
        cors: true,
        proxy: {
            '/api': {
                target: 'http://localhost:8000',
                changeOrigin: true,
            },
            '/ws': {
                target: 'ws://localhost:8000',
                ws: true,
            },
            '/frames': {
                target: 'http://localhost:8000',
                changeOrigin: true,
            },
        },
    },
    preview: {
        host: "0.0.0.0",
        port: 8501,
    },
});
