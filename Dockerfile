# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Create a non-root user and group
RUN groupadd -r celery && useradd -r -g celery celery

# Change ownership of the application directory to the non-root user
RUN chown -R celery:celery /app

# Switch to the non-root user
USER celery

# Run the Celery worker
CMD ["celery", "-A", "app.celery_app", "worker", "--loglevel=info"]

