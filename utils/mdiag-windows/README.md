MongoDB Support Tools
=====================

mdiag.ps1
---------

### Description

[mdiag.ps1](https://raw.githubusercontent.com/mongodb/support-tools/master/mdiag-windows/mdiag.ps1) is a utility to gather a wide variety of system and hardware diagnostic information.

### Usage

The easiest way to run the script is by right clicking it and selecting '**Run with PowerShell**'. Note that if you are prompted for an Execution Policy Change, pressing [Y] will allow the script to run **one time**.

Alternatively you can launch the script from a Windows command prompt. Example command line to permit script execution:  

```
powershell -ExecutionPolicy Unrestricted -File "~\Downloads\mdiag.ps1" _casereference_
```

- Replace `_casereference_` with your support case reference, if relevant.
- This script may trigger a UAC consent prompt to which the user will need to click Yes. 
   - Although the script will still run if UAC elevation is denied, it may provide less output.
- As the script progresses it will log all output to a file named `mdiag-%COMPUTERNAME%.txt` in the current users `Documents` folder.
- Once diagnostic capture completes all files will be zipped into `mdiag-%COMPUTERNAME%.zip` under the same `Documents` folder. 

### License

[Apache 2.0](http://www.apache.org/licenses/LICENSE-2.0)


DISCLAIMER
----------
Please note: all tools/scripts in this repo are released for use "AS IS" **without any warranties of any kind**, including, but not limited to their installation, use, or performance.  We disclaim any and all warranties, either express or implied, including but not limited to any warranty of noninfringement, merchantability, and/or fitness for a particular purpose.  We do not warrant that the technology will meet your requirements, that the operation thereof will be uninterrupted or error-free, or that any errors will be corrected.

Any use of these scripts and tools is **at your own risk**.  There is no guarantee that they have been through thorough testing in a comparable environment and we are not responsible for any damage or data loss incurred with their use.

You are responsible for reviewing and testing any scripts you run *thoroughly* before use in any non-testing environment.

Thanks,  
The MongoDB Support Team
