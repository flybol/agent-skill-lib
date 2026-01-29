import { defineConfig } from "vite"

export default defineConfig({
    server: {
        host: "0.0.0.0",
        port: 8501,
        strictPort: true,
        allowedHosts: ["coachagent.datacool.fun"],
    },
})
