
# Create the overall gemspec
spec = Gem::Specification.new do |s|
  s.name = 'openc3-cosmos-tool-calendar'
  s.summary = 'OpenC3 COSMOS Calendar Tool'
  s.description = <<-EOF
    Calendar view of timelines, activities, notes and metadata. Schedules
    commands and scripts to run at a future date and time.
  EOF
  s.authors = ['Ryan Melton', 'Jason Thomas']
  s.email = ['ryan@openc3.com', 'jason@openc3.com']
  s.homepage = 'https://github.com/OpenC3/cosmos'

  s.platform = Gem::Platform::RUBY
  s.required_ruby_version = '>= 3.0'

  if ENV['VERSION']
    s.version = ENV['VERSION'].dup
  else
    time = Time.now.strftime("%Y%m%d%H%M%S")
    s.version = '0.0.0' + ".#{time}"
  end
  s.licenses = ['AGPL-3.0-only', 'Nonstandard']

  s.files = Dir.glob("{targets,lib,tools,microservices}/**/*") + %w(Rakefile LICENSE.txt README.md plugin.txt)
end
