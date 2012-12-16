Android Sources Eclipse site generator
======================================

This is a simple script to generate your own Eclipse update site containing
a plugin that attaches the Android source bundle to your own projects once
installed.

This is heavily inspired by
[ADT-Addons](http://code.google.com/p/adt-addons/) but sadly it has not
been updated in a long while.  Given that the code involved is not really
that much and I found myself with some extra spare time, I just wrote a
generator that uses the currently installed Android source bundles.  This
means that anybody can host his/her own source plugin site.

The usage is pretty simple, for a site that's ready to be hosted somewhere,
just run `generate.py` passing the directory of the Android SDK
installation, a target directory for the update site, and a version (to
avoid clashing with old versions of ADT-Addons):

	./generate.py ADT_SDK_DIR TARGET_DIR VERSION

However, if you want to create a zipfile to host on a FTP/CIFS/NFS server,
add -z to the parameters and choose a file instead of a directory:

	./generate.py -z ADT_SDK_DIR TARGET_ZIP VERSION

For more options, run:

	./generate.py -h
