MongoDB Windows SSL toolkit
===========================

## Convert-PfxToPem.ps1

Windows PowerShell script that converts Windows PFX certificates (PKCS#12) into PEM (PKCS#8) format for use with MongoDB. 

To use an X.509 certificate contained in a Windows Certificate Store, export the certificate as a `.pfx` (including the private key) and use this script to convert it into a MongoDB compatible format.

Command line syntax:

`Convert-PfxToPem.ps1 [-PFXFile] <string> [[-PEMFile] <string>] [-Passphrase <string>] [-Overwrite]`

Required parameters:

* `-PFXFile <path>` - Path of the Windows PFX certificate to convert.

Optional parameters:

- `-PEMFile <path>` - Path of the PEM certificate to output.
  * If this is not supplied you will be prompted interactively.
- `-Passphase <passphrase>` - Supply this if the private key of the PFX is password protected.
- `-Overwrite` - Add this switch to overwrite any existing PEMFile.

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

