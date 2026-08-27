MongoDB Support Tools
=====================

mdiag.sh
--------

### Description

mdiag.sh is a utility to gather a wide variety of system and hardware diagnostic information.

### Usage

```
sudo bash mdiag.sh _casereference_
```

- Running without sudo (ie. as a regular user) is possible, but less information will be collected.
- It is not necessary to `chmod` the script.
- Bash version 4.0 or later is required.
- Replace `_casereference_` with your support case reference, if relevant.
- The program will generate an output file in `/tmp/mdiag-$HOSTNAME.json` with the information.

### License

[Apache 2.0](http://www.apache.org/licenses/LICENSE-2.0)


DISCLAIMER
----------
We provide these tools and scripts "as is" to assist you, without any express or implied warranties. We can't guarantee that they'll perfectly meet your specific needs in every case or that they won't have unexpected effects on any specific deployment, so please test them thoroughly in a non-production environment first. With these resources, you're solely responsible for their use. We appreciate your understanding and careful usage.

Thanks,  
The MongoDB Support Team
