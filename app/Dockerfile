FROM node:20-alpine

WORKDIR /usr/src/app

# Install dependencies
COPY package.json package-lock.json* ./
RUN npm ci --omit=dev || npm i --omit=dev

# Copy application code
COPY . .

# Set environment
ENV PORT=8080
EXPOSE 8080

# Start application
CMD ["npm", "start"]
