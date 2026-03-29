FROM python:3.10-slim

# Install minimal system dependencies (supervisor for process management)
RUN apt-get update && apt-get install -y \
    curl \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# Set timezone to Europe/Madrid (Barcelona)
ENV TZ=Europe/Madrid
RUN ln -snf /usr/share/zoneinfo/Europe/Madrid /etc/localtime && echo "Europe/Madrid" > /etc/timezone

# Set up the working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Copy supervisord config
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Create the data directory if it doesn't exist (for state.json)
RUN mkdir -p data

# Expose the port
EXPOSE 10000

# Start supervisor which will manage both Web and Worker
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
