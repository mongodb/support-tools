# ==================== #
# Convert-PfxToPem.ps1 # Copyright MongoDB, Inc, 2016, 2017
# ==================== #

<#
   .SYNOPSIS
     Convert PFX certificate to PEM format
   .DESCRIPTION 
     Convert Windows PFX certificates (PKCS#12) into PEM (PKCS#8) 
     format for use with MongoDB. There are no external 
     dependencies for running this script.
   .PARAMETER PFXFile
     Path of the PFX file to be converted.
   .PARAMETER PEMFile
     Path to write the new PEM file to.
   .PARAMETER Passphrase
     Private key passphrase, if applicable.
   .PARAMETER Overwrite
     Clobber any existing file when writing the PEM key file.
#>

#
# DISCLAIMER
#
# Please note: all tools/ scripts in this repo are released for use "AS IS" without any warranties of any kind, 
# including, but not limited to their installation, use, or performance. We disclaim any and all warranties, either 
# express or implied, including but not limited to any warranty of noninfringement, merchantability, and/ or fitness 
# for a particular purpose. We do not warrant that the technology will meet your requirements, that the operation 
# thereof will be uninterrupted or error-free, or that any errors will be corrected.
#
# Any use of these scripts and tools is at your own risk. There is no guarantee that they have been through thorough 
# testing in a comparable environment and we are not responsible for any damage or data loss incurred with their use.
#
# You are responsible for reviewing and testing any scripts you run thoroughly before use in any non-testing environment.
#
#
# LICENSE
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with 
# the License. You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on 
# an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the 
# specific language governing permissions and limitations under the License.
#

Param(
     [Parameter(Mandatory=$true, Position=1, HelpMessage="Enter the PFX certificate file you wish to convert.")]
     [string] $PFXFile,

     [string] $Passphrase = '',

     [Parameter(Mandatory=$false, Position=2)]     
     [string] $PEMFile,
     
     [switch] $Overwrite = $false
)

Add-Type @'
   using System;
   using System.Security.Cryptography;
   using System.Security.Cryptography.X509Certificates;
   using System.Collections.Generic;
   using System.Text;

   public class MongoDB_Utils
   {
      public const int Base64LineLength = 64;

      private static byte[] EncodeInteger(byte[] value)
      {
         var i = value;

         if (value.Length > 0 && value[0] > 0x7F)
         {
            i = new byte[value.Length + 1];
            i[0] = 0;
            Array.Copy(value, 0, i, 1, value.Length);
         }

         return EncodeData(0x02, i);
      }

      private static byte[] EncodeLength(int length)
      {
         if (length < 0x80)
            return new byte[1] { (byte)length };

         var temp = length;
         var bytesRequired = 0;
         while (temp > 0)
         {
            temp >>= 8;
            bytesRequired++;
         }

         var encodedLength = new byte[bytesRequired + 1];
         encodedLength[0] = (byte)(bytesRequired | 0x80);

         for (var i = bytesRequired - 1; i >= 0; i--)
            encodedLength[bytesRequired - i] = (byte)(length >> (8 * i) & 0xff);

         return encodedLength;
      }

      private static byte[] EncodeData(byte tag, byte[] data)
      {
         List<byte> result = new List<byte>();
         result.Add(tag);
         result.AddRange(EncodeLength(data.Length));
         result.AddRange(data);
         return result.ToArray();
      }
       
      public static string RsaPrivateKeyToPem(RSAParameters privateKey)
      {
         // Version: (INTEGER)0 - v1998
         var version = new byte[] { 0x02, 0x01, 0x00 };

         // OID: 1.2.840.113549.1.1.1 - with trailing null
         var encodedOID = new byte[] { 0x30, 0x0D, 0x06, 0x09, 0x2A, 0x86, 0x48, 0x86, 0xF7, 0x0D, 0x01, 0x01, 0x01, 0x05, 0x00 };

         List<byte> privateKeySeq = new List<byte>();

         privateKeySeq.AddRange(version);
         privateKeySeq.AddRange(EncodeInteger(privateKey.Modulus));
         privateKeySeq.AddRange(EncodeInteger(privateKey.Exponent));
         privateKeySeq.AddRange(EncodeInteger(privateKey.D));
         privateKeySeq.AddRange(EncodeInteger(privateKey.P));
         privateKeySeq.AddRange(EncodeInteger(privateKey.Q));
         privateKeySeq.AddRange(EncodeInteger(privateKey.DP));
         privateKeySeq.AddRange(EncodeInteger(privateKey.DQ));
         privateKeySeq.AddRange(EncodeInteger(privateKey.InverseQ));

         List<byte> privateKeyInfo = new List<byte>();
         privateKeyInfo.AddRange(version);
         privateKeyInfo.AddRange(encodedOID);
         privateKeyInfo.AddRange(EncodeData(0x04, EncodeData(0x30, privateKeySeq.ToArray())));

         StringBuilder output = new StringBuilder();

         var encodedPrivateKey = EncodeData(0x30, privateKeyInfo.ToArray());
         var base64Encoded = Convert.ToBase64String(encodedPrivateKey, 0, (int)encodedPrivateKey.Length);
         output.AppendLine("-----BEGIN PRIVATE KEY-----");

         for (var i = 0; i < base64Encoded.Length; i += Base64LineLength)
            output.AppendLine(base64Encoded.Substring(i, Math.Min(Base64LineLength, base64Encoded.Length - i)));

         output.Append("-----END PRIVATE KEY-----");
         return output.ToString();
      }

      public static string PfxCertificateToPem(X509Certificate2 certificate)
      {
         var certBase64 = Convert.ToBase64String(certificate.Export(X509ContentType.Cert));

         var builder = new StringBuilder();
         builder.AppendLine("-----BEGIN CERTIFICATE-----");

         for (var i = 0; i < certBase64.Length; i += MongoDB_Utils.Base64LineLength)
            builder.AppendLine(certBase64.Substring(i, Math.Min(MongoDB_Utils.Base64LineLength, certBase64.Length - i)));

         builder.Append("-----END CERTIFICATE-----");
         return builder.ToString();
      }
   }
'@
try
{
   if (Test-Path -Path $PFXFile -PathType Leaf)
   {
      $pfxPath = (Get-Item -Path $PFXFile).FullName
   }
   else
   {
      Write-Warning "Unable to find PFX file $PFXFile"
      Exit
   }
}
catch
{
   Write-Warning "Unable to acces PFX file $PFXFile"
   Exit
}

try
{
   if (-not ($cert = New-Object Security.Cryptography.X509Certificates.X509Certificate2($pfxPath, $Passphrase, 'Exportable')))
   {
      Write-Warning "Unable to load certificate $PFXFile"
      Exit
   }
}
catch
{
   Write-Warning "Unable to load certificate $PFXFile - $($_.Exception.Message)"
   Exit
}

if (-not $cert.HasPrivateKey) 
{
   Write-Warning "No private key present for $($cert.SubjectName.Name)"
   Exit
}

if (-not $cert.PrivateKey.CspKeyContainerInfo.Exportable)
{
   Write-Warning "Cannot find exportable private key for $($cert.SubjectName.Name)"
   Exit
}

$result = [MongoDB_Utils]::PfxCertificateToPem($cert)

$parameters = ([Security.Cryptography.RSACryptoServiceProvider] $cert.PrivateKey).ExportParameters($true)
$result += "`r`n" + [MongoDB_Utils]::RsaPrivateKeyToPem($parameters);

if (-not $PEMFile)
{
   $defaultFilename = [IO.File]::GetFileNameWithoutExtension($PFXFile) + ".pem"
   if (-not ($PEMFile = Read-Host "Provide full path for PEM certificate output, or press [ENTER] to use $defaultFilename"))
   {
      $PEMFile = "$($pwd.Path)\$defaultFilename"
   }
}
 
try
{
   if ($Overwrite)
   {
      $result | Out-File -Encoding ASCII -ErrorAction Stop $PEMFile
   }
   else
   {
      $result | Out-File -Encoding ASCII -ErrorAction Stop -NoClobber $PEMFile
   }
   
   Write-Host "PEM certficate written to $PEMFile"
}
catch
{
   Write-Warning "Error writing to $PEMFile - $($_.Exception.Message)"
}