import { defineConfig } from "vite"

export default defineConfig({
    server: {
        allowedHosts: ["coachagent.datacool.fun"],
        host: '0.0.0.0', // 监听所有网络接口，允许局域网访问
        port: 8501,       // 开发服务器端口
        strictPort: false, // 如果端口被占用，自动尝试下一个端口
    },
});
