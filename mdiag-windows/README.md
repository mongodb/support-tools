MongoDB Support Tools
=====================

mdiag.ps1
---------

### Description

mdiag.ps1 is a Windows PowerShell script to gather a wide variety of system-level diagnostic information.


## Usage

The easiest way to run the script is by right clicking it and selecting 'Run with PowerShell'. 

Alternatively you can launch it from the Run dialog (Win+R) by typing the following command and pressing `Enter`:
```bat
powershell -ExecutionPolicy Unrestricted -File "<full-path-to-mdiag.ps1>" SF-XXXXXX
```

This may trigger a UAC dialog to which the user will need to click Yes. Although the script will still run if UAC elevation is denied, it may provide less output.

As the script progresses it will fill a text file in the Documents folder of the current user. The file is named "mdiag-\<hostname\>.txt". 

Once the collection process is complete this text file along with other files collected will be added to a zip file named "mdiag-\<hostname\>.zip" under the same Documents folder. 


### License

DISCLAIMER
----------
Please note: all tools/scripts in this repo are released for use "AS IS" **without any warranties of any kind**, including, but not limited to their installation, use, or performance.  We disclaim any and all warranties, either express or implied, including but not limited to any warranty of noninfringement, merchantability, and/or fitness for a particular purpose.  We do not warrant that the technology will meet your requirements, that the operation thereof will be uninterrupted or error-free, or that any errors will be corrected.

Any use of these scripts and tools is **at your own risk**.  There is no guarantee that they have been through thorough testing in a comparable environment and we are not responsible for any damage or data loss incurred with their use.

You are responsible for reviewing and testing any scripts you run *thoroughly* before use in any non-testing environment.

Thanks, 
The MongoDB Support Team
