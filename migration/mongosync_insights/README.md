# Mongosync Insights

This project parses **mongosync** logs and reads the internal database (metadata), generating a variety of plots to assist with monitoring and troubleshooting ongoing mongosync migrations.

## Requirements

Mongosync Insights requires Python version 3.10+.

The `requirements.txt` file lists the Python packages on which the scripts depend. The packages are specified with their version numbers to ensure compatibility.

### System Dependencies

Before installing Python packages, you need to install `libmagic`, which is required by the `python-magic` library for MIME type validation:

#### macOS
```bash
# Using Homebrew
brew install libmagic
```

#### Linux (Ubuntu/Debian)
```bash
# Using apt
sudo apt-get update
sudo apt-get install libmagic1
```

#### Linux (RHEL/CentOS/Fedora)
```bash
# Using yum (RHEL/CentOS)
sudo yum install file-devel

# Using dnf (Fedora)
sudo dnf install file-devel
```

#### Windows
```powershell
# Using pip to install python-magic-bin (includes libmagic for Windows)
pip3 install python-magic-bin
```

**Note:** On Windows, you can use `python-magic-bin` instead of `python-magic` in the `requirements.txt` file, as it includes the necessary DLL files.

### Python Dependencies

After installing the system dependencies, install the Python packages:

```bash
pip3 install -r requirements.txt
```

Run the script in the Python environment where you want to run it. If you're using a virtual environment, activate it first.

#### Using Virtual Environment (Recommended)

```bash
# Create a virtual environment
python3 -m venv venv

# Activate the virtual environment
# On macOS/Linux:
source venv/bin/activate

# On Windows:
venv\Scripts\activate

# Install dependencies
pip3 install -r requirements.txt
```

## Getting Started

1. Download the Mongosync Insights folder.
2. Navigate to the directory containing the Python script and the `requirements.txt` file.
3. Install system dependencies (`libmagic`) as described in the [System Dependencies](#system-dependencies) section above.
4. (Optional but recommended) Create and activate a virtual environment.
5. Install Python dependencies with `pip3 install -r requirements.txt`.
6. Run the script `python3 mongosync_insights.py`.

Please note that you need Python 3.10+ and pip installed on your machine to run the script and install the dependencies.

### Quick Start Example

```bash
# Navigate to the project directory
cd mongosync_insights

# Install libmagic (macOS example)
brew install libmagic

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install Python dependencies
pip3 install -r requirements.txt

# Run the application
python3 mongosync_insights.py
```

## Troubleshooting

### libmagic Installation Issues

If you encounter errors related to `magic` or `libmagic` when running the application:

#### macOS
```bash
# Error: "ImportError: failed to find libmagic"
# Solution: Install libmagic via Homebrew
brew install libmagic

# If still having issues, try reinstalling python-magic
pip3 uninstall python-magic
pip3 install python-magic
```

#### Linux
```bash
# Error: "ImportError: failed to find libmagic"
# Solution: Install the appropriate package for your distribution

# Ubuntu/Debian
sudo apt-get install libmagic1

# RHEL/CentOS
sudo yum install file-libs
```

#### Windows
```powershell
# Error: "failed to find libmagic"
# Solution: Use python-magic-bin instead
pip3 uninstall python-magic
pip3 install python-magic-bin
```

### File Upload Issues

If you're getting errors when uploading files:

- **"Invalid File Type"**: Ensure you're uploading a valid JSON log file from mongosync. The application validates MIME types to ensure only JSON/text files are accepted.
- **"File Too Large"**: The default maximum file size is 10GB. You can adjust this by setting the `MONGOSYNC_MAX_FILE_SIZE` environment variable.
- **"Invalid JSON"**: Ensure the log file contains valid JSON lines. Non-JSON files will be rejected.

## Accessing the Application and Viewing Plots

Once the application runs, you can access it by opening a web browser and navigating to `http://localhost:3030`. It assumes the application runs on the same machine where you're opening the browser and is configured to listen on port 3030.

![Mongosync Logs Analyzer](static/mongosync_insights_home.png)

### Parsing the `mongosync` Log File

The application provides a user interface for uploading the `mongosync` log file. Clicking a "Browse" or "Choose File" button, select the file from your file system, and then click on "Open" or "Upload" button.

### Live monitoring the migration

When running for the first time, the application will provide a form requesting the target's connection string. 
Clicking the "Live Monitor" it will save the connection string in the `config.ini` and the page will refresh with the migration progress.

## Viewing the Plot Information

Once the `mongosync` data is loaded, the application processes the data and generates the plots. 

If the plots aren't visible after uploading the file, you may need to refresh the page. If the plots still aren't visible, check for any error messages or notifications from the application.

### Mongosync Logs

This script processes the Mongosync logs and generates various plots. The plots include scatter plots and tables, and they visualize different aspects of the data, such as `Total and Copied bytes`, `CEA Reads and Writes`, `Collection Copy Reads and Writes`, `Events applied`, and `Lag Time`.

![Mongosync logs analyzer](static/mongosync_log_analyzer.png)

### Mongosync Metadata

This script processes Mongosync metadata and generates various plots refreshing every 10 seconds by default. The plots visualize different aspects of the data, such as `Partitions Completed`, `Data Copied`, `Phases`, and `Collection Progress`.

![Mongosync metadata plots](static/mongosync_metadata.png)

### License

[Apache 2.0](http://www.apache.org/licenses/LICENSE-2.0)

DISCLAIMER
----------
Please note: all tools/ scripts in this repo are released for use "AS IS" **without any warranties of any kind**,
including, but not limited to their installation, use, or performance.  We disclaim any and all warranties, either 
express or implied, including but not limited to any warranty of noninfringement, merchantability, and/ or fitness 
for a particular purpose.  We do not warrant that the technology will meet your requirements, that the operation 
thereof will be uninterrupted or error-free, or that any errors will be corrected.

Any use of these scripts and tools is **at your own risk**.  There is no guarantee that they have been through 
thorough testing in a comparable environment and we are not responsible for any damage or data loss incurred with 
their use.

You are responsible for reviewing and testing any scripts you run *thoroughly* before use in any non-testing 
environment.

Thanks,  
The MongoDB Support Team
