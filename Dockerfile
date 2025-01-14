FROM python:3.11

# Set environment variable for Python unbuffered output
ENV PYTHONUNBUFFERED=1

# Install system dependencies required for Manim
RUN echo "Starting system dependencies installation..." && \
    apt-get update && \
    echo "Installing required packages..." && \
    apt-get install -y \
    ffmpeg \
    texlive \
    texlive-latex-extra \
    texlive-fonts-extra \
    texlive-latex-recommended \
    texlive-science \
    tipa \
    libcairo2-dev \
    libpango1.0-dev \
    pkg-config \
    python3-dev \
    build-essential \
    curl \
    && echo "Cleaning up apt cache..." && \
    rm -rf /var/lib/apt/lists/* && \
    echo "System dependencies installation complete."

# Set working directory
WORKDIR /app
RUN echo "Working directory set to /app"

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN echo "Copied requirements.txt to container"

# Upgrade pip first, then install dependencies
RUN echo "Starting Python dependencies installation..." && \
    pip install --no-cache-dir --upgrade pip && \
    echo "Pip upgraded successfully, installing requirements..." && \
    pip install --no-cache-dir -r requirements.txt && \
    echo "Python dependencies installation complete."

# Copy application code
COPY . .
RUN echo "Copied application code to container"

# Expose port
EXPOSE 8000
RUN echo "Exposed port 8000"

# Use RUN for the echo statement
RUN echo "Starting FastAPI application with Uvicorn..."

# Use JSON array syntax for CMD
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "debug"]