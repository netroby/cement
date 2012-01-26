"""Cement core controller module."""

import re
import textwrap
import argparse
from cement2.core import backend, exc, interface, handler, meta

Log = backend.minimal_logger(__name__)

def controller_validator(klass, obj):
    """
    Validates an handler implementation against the IController interface.
    
    """
    members = [
        'setup',
        'dispatch',
        ]
    meta = [
        'label',
        'interface',
        'description',
        'defaults',
        'arguments',
        ]
    interface.validate(IController, obj, members, meta=meta)
    
    # also check Meta.arguments values
    errmsg = "Controller arguments must be a list of tuples.  I.e. " + \
             "[ (['-f', '--foo'], dict(action='store')), ]"
    try:
        for _args,_kwargs in obj._meta.arguments:
            if not type(_args) is list:
                raise exc.CementInterfaceError(errmsg)
            if not type(_kwargs) is dict:
                raise exc.CementInterfaceError(errmsg)
    except ValueError:
        raise exc.CementInterfaceError(errmsg)
            
class IController(interface.Interface):
    """
    This class defines the Controller Handler Interface.  Classes that 
    implement this handler must provide the methods and attributes defined 
    below.
    
    Implementations do *not* subclass from interfaces.
    
    Usage:
    
    .. code-block:: python
    
        from cement2.core import controller
        
        class MyBaseController(object):
            class Meta:
                interface = controller.IController
                label = 'my_base_controller'
            ...
            
    """
    class IMeta:
        label = 'controller'
        validator = controller_validator
    
    # Must be provided by the implementation
    Meta = interface.Attribute('Handler Meta-data')
    registered_controllers = interface.Attribute('List of registered controllers')
    
    def setup(base_app):
        """
        The setup function is after application initialization and after it
        is determined that this controller was requested via command line
        arguments.  Meaning, a controllers setup() function is only called
        right before it's dispatch() function is called to execute a command.
        Must 'setup' the handler object making it ready for the framework
        or the application to make further calls to it.
        
        Required Arguments:
        
            base_app
                The application object, after it has been setup() and run().
                
        Returns: n/a
        
        """
    
    def dispatch(self):
        """
        Reads the application object's data to dispatch a command from this
        controller.  For example, reading self.app.pargs to determine what
        command was passed, and then executing that command function.
                
        """

class expose(object):
    def __init__(self, hide=False, help='', aliases=[]):
        """
        Used to expose controller functions to be listed as commands, and to 
        decorate the function with Meta data for the argument parser.
        
        Optional Argumnets:
        
            hide
                Whether the command should be visible
            
            help
                Help text.
            
            aliases
                List of aliases to this command.
             
        Usage:
        
        .. code-block:: python
        
            from cement2.core import controller
           
            class MyAppBaseController(controller.CementBaseController):
                class Meta:
                    interface = controller.IController
                    label = 'base'
                    description = 'MyApp is awesome'
                    defaults = dict()
                    arguments = []
                    
                @controller.expose(hide=True, aliases=['run'])
                def default(self):
                    print("In MyAppBaseController.default()")
       
                @controller.expose()
                def my_command(self):
                    print("In MyAppBaseController.my_command()")
                   
        """
        self.hide = hide
        self.help = help
        self.aliases = aliases
        
    def __call__(self, func):
        self.func = func
        self.func.label = self.func.__name__
        self.func.exposed = True
        self.func.hide = self.hide
        self.func.help = self.help
        self.func.aliases = self.aliases
        return self.func

class CementBaseController(meta.MetaMixin):
    """
    This is an implementation of the IControllerHandler interface, but as a
    base class that application controllers need to subclass from.  
    Registering it directly as a handler is useless.
    
    NOTE: This handler *requires* that the applications 'arg_handler' be
    argparse.  If using an alternative argument handler you will need to 
    write your own controller.
    
    Usage:
    
    .. code-block:: python
    
        from cement2.core import controller
           
        class MyAppBaseController(controller.CementBaseController):
            class Meta:
                interface = controller.IController
                label = 'base'
                description = 'MyApp is awesome'
                defaults = dict()
                arguments = []
                epilog = "This is the text at the bottom of --help."
            ...
        
    Supported Meta Data:
    
        interface
            The interface that this controller implements (IController).
            
        label
            The label of the controller.  Will be used as the sub-command
            name for 'stacked' controllers.
            
        description
            The description showed at the top of '--help'.
            
        defaults
            Configuration defaults (type: dict) that are merged into 
            config->'controller' where controller is the label defined above.
            
        arguments
            Arguments to pass to the argument_handler.  The format is a list
            of tuples whos items are a ( list, dict ).  Meaning:
            
                [ ( ['-f', '--foo'], dict(dest='foo', help='foo option') ), ]

        epilog
            The text that is displayed at the bottom when '--help' is passed.
            
    """
    class Meta:
        interface = IController
        label = 'base' # provided in subclass
        description = 'Cement Base Controller'
        defaults = {} # default config options
        arguments = [] # list of tuple (*args, *kwargs)
        stacked_on = None # controller name to merge commands/options into
        hide = False # whether to hide controller completely
        epilog = None
        
    ### FIX ME: What is this used for???
    ignored = ['visible', 'hidden', 'exposed']
          
    def __init__(self, *args, **kw):
        super(CementBaseController, self).__init__(*args, **kw)
        
        self.app = None
        self.command = 'default'
        self.config = None
        self.log = None
        self.pargs = None
        self.visible = {}
        self.hidden = {}
        self.exposed = {}
        self.arguments = []
        
    def setup(self, base_app):
        # shortcuts
        self.app = base_app                        
        self.config = self.app.config
        self.log = self.app.log
        self.pargs = self.app.pargs
        self.render = self.app.render
        self._collect()
             
    def _parse_args(self):
        """
        Parse command line arguments and determine a command to dispatch.
        
        """
        # chop off a command argument if it matches an exposed command
        if len(self.app.argv) > 0 and not self.app.argv[0].startswith('-'):
            
            # translate dashes back to underscores
            cmd = re.sub('-', '_', self.app.argv[0])
            if cmd in self.exposed:
                self.command = cmd
                self.app.argv.pop(0)
            else:
                for label in self.exposed:
                    func = self.exposed[label]
                    if self.app.argv[0] in func['aliases']:
                        self.command = func['label']
                        self.app.argv.pop(0)
                        break
                        
        self.app.args.description = self.help_text
        self.app.args.usage = self.usage_text
        self.app.args.formatter_class=argparse.RawDescriptionHelpFormatter

        self.app._parse_args()
        self.pargs = self.app.pargs
        
    def dispatch(self):
        """
        Takes the remaining arguments from self.app.argv and parses for a
        command to dispatch, and if so... dispatches it.
        
        """
        self._add_arguments_to_parser()
        self._parse_args()
                       
        if not self.command:
            Log.debug("no command to dispatch")
        else:    
            func = self.exposed[self.command]     
            Log.debug("dispatching command: %s.%s" % \
                      (func['controller'], func['label']))
            
            if func['controller'] == self.Meta.label:
                getattr(self, func['label'])()
            else:
                controller = handler.get('controller', func['controller'])()
                controller.setup(self.app)
                getattr(controller, func['label'])()

    @expose(hide=True, help='default command')
    def default(self):
        """
        This is the default action if no arguments (sub-commands) are passed
        at command line.
        
        """
        raise NotImplementedError
    
    def _add_arguments_to_parser(self):
        """
        Run after _collect().  Add the collected arguments to the apps
        argument parser.
        
        """
        for _args,_kwargs in self.arguments:
            self.app.args.add_argument(*_args, **_kwargs)
        
    def _collect_from_self(self):
        """
        Collect arguments from this controller.
        """
        # collect our Meta arguments
        for _args,_kwargs in self.Meta.arguments:
            self.arguments.append((_args, _kwargs))
           
        # epilog only good for non-stacked controllers
        if hasattr(self.Meta, 'epilog'):
            if  not hasattr(self.Meta, 'stacked_on') or \
                not self.Meta.stacked_on:
                self.app.args.epilog = self.Meta.epilog
             
        # collect exposed commands from ourself
        for member in dir(self):
            if member in self.ignored or member.startswith('_'):
                continue
                
            func = getattr(self, member)
            if hasattr(func, 'exposed'):
                func_dict = dict(
                    controller=self.Meta.label,
                    label=func.label,
                    help=func.help,
                    aliases=func.aliases,
                    hide=func.hide,
                    )

                if func_dict['label'] == self.Meta.label:
                    raise exc.CementRuntimeError(
                        "Controller command '%s' " % func_dict['label'] + \
                        "matches controller label.  Use 'default' instead."
                        )
                
                self.exposed[func.label] = func_dict
                    
                if func.hide:
                    self.hidden[func.label] = func_dict
                else:
                    if not getattr(self.Meta, 'hide', None):
                        self.visible[func.label] = func_dict
                        
    def _collect_from_non_stacked_controller(self, controller):
        """
        Collect arguments from non-stacked controllers.
        
        Required Arguments:
        
            controller
                The controller to collect arguments from.
                
        """
        Log.debug('exposing %s controller' % controller.Meta.label)
                
        func_dict = dict(
            controller=controller.Meta.label,
            label=controller.Meta.label,
            help=controller.Meta.description,
            aliases=[],
            hide=False,
            )
        # expose the controller label as a sub command
        self.exposed[controller.Meta.label] = func_dict
        if not getattr(controller.Meta, 'hide', None):
            self.visible[controller.Meta.label] = func_dict
                            
    def _collect_from_stacked_controller(self, controller):     
        """
        Collect arguments from stacked controllers.
        
        Required Arguments:
        
            controller
                The controller to collect arguments from.
                
        """           
        contr = controller()
        contr.setup(self.app)
        contr._collect()
        
        # add stacked arguments into ours
        for _args,_kwargs in contr.arguments:
            self.arguments.append((_args, _kwargs))
            
        # add stacked commands into ours              

        # determine hidden vs. visible commands
        func_dicts = contr.exposed
        for label in func_dicts:
            if label in self.exposed:  
                if label == 'default':
                    Log.debug(
                        "ignoring duplicate command '%s' " % label + \
                        "found in '%s' " % controller.Meta.label + \
                        "controller."
                        )
                    continue
                else:
                    raise exc.CementRuntimeError(
                        "Duplicate command '%s' " % label + \
                        "found in '%s' " % controller.Meta.label + \
                        "controller."
                        )
            if func_dicts[label]['hide']:
                self.hidden[label] = func_dicts[label]
            elif not getattr(controller.Meta, 'hide', False):
                self.visible[label] = func_dicts[label]
            self.exposed[label] = func_dicts[label]

    def _collect_from_controllers(self):
        """
        Collect arguments from all controllers.
        
        """
        for controller in handler.list('controller'):
            if controller.Meta.label == self.Meta.label:
                continue
                
            # expose other controllers as commands also
            if not hasattr(controller.Meta, 'stacked_on') \
               or controller.Meta.stacked_on is None:
                # only show non-stacked controllers under base
                if self.Meta.label == 'base':
                    self._collect_from_non_stacked_controller(controller)                        
            elif controller.Meta.stacked_on == self.Meta.label:
                self._collect_from_stacked_controller(controller)

    def _collect(self):
        """
        Collects all commands and arguments from this controller, and other
        availble controllers.
        """
        
        Log.debug("collecting arguments and commands from '%s' controller" % \
                  self)
                  
        self.visible = {}
        self.hidden = {}
        self.exposed = {}
        self.arguments = []
        
        self._collect_from_self()
        self._collect_from_controllers()
        self._check_for_duplicates_on_aliases()
        
    def _check_for_duplicates_on_aliases(self):
        for label in self.exposed:
            func = self.exposed[label]
            for alias in func['aliases']:
                if alias in self.exposed.keys():
                    raise exc.CementRuntimeError(
                        "Alias '%s' " % alias + \
                        "from the '%s' controller " % func['controller'] + \
                        "colides with the " + \
                        "'%s' " % self.exposed[alias]['controller'] + \
                        "controller."
                        )
                        
    @property
    def usage_text(self):
        """
        Returns the usage text displayed when '--help' is passed.
        
        """
        if self.Meta.label == 'base':
            txt = "%s <CMD> -opt1 --opt2=VAL [arg1] [arg2] ..." % \
                self.app.args.prog
        else:
            txt = "%s %s <CMD> -opt1 --opt2=VAL [arg1] [arg2] ..." % \
                  (self.app.args.prog, self.Meta.label)
        return txt
        
    @property
    def help_text(self):
        """
        Returns the help text displayed when '--help' is passed.
        
        """
        cmd_txt = ''
        
        # hack it up to keep commands in alphabetical order
        sorted_labels = []
        for label in list(self.visible.keys()):
            old_label = label
            label = re.sub('_', '-', label)
            sorted_labels.append(label)
            
            if label != old_label:
                self.visible[label] = self.visible[old_label]
                del self.visible[old_label]
        sorted_labels.sort()
        
        for label in sorted_labels:
            func = self.visible[label]
            if len(func['aliases']) > 0:
                cmd_txt = cmd_txt + "  %s (aliases: %s)\n" % \
                            (label, ', '.join(func['aliases']))
            else:
                cmd_txt = cmd_txt + "  %s\n" % label
            
            if func['help']:
                cmd_txt = cmd_txt + "    %s\n\n" % func['help']
            else:
                cmd_txt = cmd_txt + "\n"
    
        txt = '''%s

commands:

%s

        
        ''' % (self.Meta.description, cmd_txt)
        
        return textwrap.dedent(txt)        
