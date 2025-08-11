### MongoDB Support Tools
=====================

# 🛠️ MongoDB Atlas User & Role Migration Tool

This tool provides a Node.js-based CLI utility to **migrate database users and custom roles** from one MongoDB Atlas project to another using the [Atlas Admin API](https://www.mongodb.com/docs/atlas/reference/api-resources-spec/v2/).

---

## 📦 Prerequisites

Before using this tool, ensure you have:

- Node.js installed (v16 or above)
- MongoDB Atlas Public and Private API Keys
- Source Project ID and Destination Project ID
- Network access to `https://cloud.mongodb.com`

---

## 🚀 Getting Started

1. **Clone or Download the Repository**

   ```bash
   git clone https://github.com/mongodb/support-tools/migrate-users-between-project
   cd migrate-users
  
2. **Install Dependencies**

   ```bash
   npm install

3. **Configure Your Environment**

Edit the relevant variables inside config.js:

- publicKey
- privateKey
- sourceProjectId
- destinationProjectId

4. **Run the Migration**
   ```bash
     node runMigrations.js


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