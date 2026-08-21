# encoding: ascii-8bit

###############################################################################
# Copyright (c) ATTX, Inc. 2026. All Rights Reserved.
#
# This software and associated documentation (the "Software") are the
# proprietary and confidential information of ATTX, Inc. The Software is
# furnished under a license agreement between ATTX and the user organization
# and may be used or copied only in accordance with the terms of the agreement.
# Refer to 'license/attx_license.adoc' for standard license terms.
#
# EXPORT CONTROL NOTICE: THIS SOFTWARE MAY INCLUDE CONTENT CONTROLLED UNDER THE
# INTERNATIONAL TRAFFIC IN ARMS REGULATIONS (ITAR) OR THE EXPORT ADMINISTRATION
# REGULATIONS (EAR99). No part of the Software may be used, reproduced, or
# transmitted in any form or by any means, for any purpose, without the express
# written permission of ATTX, Inc.
###############################################################################

# Create the overall gemspec
Gem::Specification.new do |s|
  s.name = 'openc3-cosmos-warplink'
  s.summary = 'OpenC3 COSMOS WarpLink plugin'
  s.description = <<-EOF
    WarpLink plugin for WarpOS flight software, deployed to OpenC3 COSMOS
  EOF
  # Proprietary: 'Nonstandard' is RubyGems' marker for a non-SPDX license.
  # Terms are in LICENSE.txt, shipped in the gem via s.files below.
  s.license = 'Nonstandard'
  s.authors = ['Alex Jackson']
  s.email = ['alex.jackson@warpware.co']
  s.homepage = 'https://github.com/OpenC3/cosmos'
  s.platform = Gem::Platform::RUBY
  s.required_ruby_version = '>= 3.0'

  if ENV['VERSION']
    s.version = ENV['VERSION'].dup
  else
    time = Time.now.strftime("%Y%m%d%H%M%S")
    s.version = '0.0.0' + ".#{time}"
  end
  s.files = Dir.glob("{targets,lib,tools,microservices}/**/*") + %w(Rakefile README.md LICENSE.txt plugin.txt)
end
