// postcss.config.js                     ← replace the whole file
import tailwind from '@tailwindcss/postcss';
import autoprefixer from 'autoprefixer';

export default {
  plugins: [
    tailwind,          // ⬅️ new package
    autoprefixer
  ]
};
