import type { Config } from "tailwindcss";

export default {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        ink: "#080a0d",
        panel: "#101318",
        line: "#242930",
        acid: "#d8ff5f",
        coral: "#ff7557",
      },
      boxShadow: { glow: "0 0 40px rgba(216,255,95,.12)" },
    },
  },
  plugins: [],
} satisfies Config;

