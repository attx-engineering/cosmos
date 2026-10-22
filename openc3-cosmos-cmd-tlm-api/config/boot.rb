ENV["BUNDLE_GEMFILE"] ||= File.expand_path("../Gemfile", __dir__)

require "bundler/setup" # Set up gems listed in the Gemfile.
# Speed up boot time by caching expensive operations. Not while coverage runs,
# as the specs run it: bootsnap refuses to compile then ("should not compile
# with coverage"), and no spec could load.
require "bootsnap/setup" unless defined?(Coverage) && Coverage.running?
