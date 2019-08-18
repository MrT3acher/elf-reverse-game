from lief import ELF
from termcolor import colored
import subprocess
import random
import shutil
import os
import argparse
import argcomplete
import click
from argcomplete.completers import EnvironCompleter

parser = argparse.ArgumentParser()
parser.add_argument('-v', '--verbose', help='verbose', action='store_true', required=False).completer = EnvironCompleter
parser.add_argument('-f', '--folder', help='training folder path to create training files there', default='./training-folder').completer = EnvironCompleter
argcomplete.autocomplete(parser)
args = parser.parse_args()

def verbose_print(string: str) -> None:
    if args.verbose:
        print("[v] " + string)
def alert_print(string: str) -> None:
    print(colored('[X] ' + string, 'red'))
def info_print(string: str) -> None:
    print(colored('[!] ' + string, 'blue'))

def find_executables(path: str) -> list:
    # define the ls command
    result = subprocess.Popen(("find " + path + " -executable -type f").split(' '), stdout=subprocess.PIPE)

    # read from the end of the pipe (stdout)
    pipe_end = result.stdout
    files_list = pipe_end.read().decode()

    # output the files line by line
    files = files_list.split("\n")
    files.pop() # remove the last empty file

    return files

class Game:
    score = 0
    asked = 0
    binaries = []
    questions = []
    binary = None
    overwrite_folder = None

    def __init__(self):
        if Game.overwrite_folder == None:
            if os.path.exists(args.folder):
                alert_print('The folder path exists (you can use -f option to specify a manual training folder name)')
                Game.overwrite_folder = click.confirm("Do you want to use existing folder?")
                if not Game.overwrite_folder:
                    exit(0)
            else:
                os.mkdir(args.folder)
                verbose_print('Folder %s created' % args.folder)
 
        if len(Game.binaries) == 0:
            Game.binaries = find_executables("/bin")
            Game.binaries.append(find_executables("/usr/bin"))

        binpath = ''
        while True:
            r = random.randrange(0, len(Game.binaries))
            binpath = Game.binaries[r]
            if ELF.parse(binpath) is not None:
                break
                
        shutil.copy(binpath, args.folder)
        filename = binpath.split('/')[-1]
        newbinpath = '/'.join(args.folder.split('/') + [filename])
        Game.binary = ELF.parse(newbinpath)
        
        verbose_print("Found a binary: " + binpath)
        info_print('Training binary files is: ' + newbinpath)
        verbose_print('Found binary copied to training folder')
        
    def ask_random_question(self) -> None:
        i = random.randrange(0, len(Game.questions))
        Game.questions[i].ask()
        info_print('Your score: {}/{}'.format(Game.score, Game.asked))


class Question:
    def __init__(self, question: str, answer: callable, before: callable = None):
        #assert type(question) == str, 'Question must be str'
        #assert callable(answer), 'Answer must be a function (callable)'
        #assert callable(before), 'Before must be a function (callable)'

        self.question = question
        self.answer = answer
        self.before = before

    def ask(self) -> None:
        Game.asked += 1
       
        if self.before is not None:
            self.before()

        self._ask()

    def _get_answer(self, question): 
        answer = input(colored('[?] ' + question + '\n : ', 'cyan'))
        return answer

    def _check_answer(self, answer, *args):
        if self.answer(answer, *args):
            Game.score += 1
            print(colored('[True]', 'green'))
        else:
            print(colored('[False]', 'red'))

    def _ask(self):
        # show question and get answer
        answer = self._get_answer(self.question)
        
        # check answer
        self._check_answer(answer)



class DynamicQuestion(Question):
    REPLACE_SYMBOL = '%&%'

    def __init__(self, question, answer, before, *args):
        super(DynamicQuestion, self).__init__(question, answer, before)

        assert (answer.__code__.co_argcount - 1) == len(args) == question.count(self.REPLACE_SYMBOL), \
               'Answer function need to have arguments as mush as the number of ' + self.REPLACE_SYMBOL + ' symbols plus 1 in the question text'
        assert all(map(lambda func: callable(func), args)), 'All *args elements must be function (callable)'

        self.args = args

    def _ask(self):
        # store parameters created by *args function for passing to answer function
        parameters = []

        # replace each REPLACE_SYMBOL with result of its peer function in *args
        ready_question = self.question
        for i in range(len(self.args)):
            parameters.append(self.args[i]())
            ready_question = ready_question.replace(self.REPLACE_SYMBOL, str(parameters[i]), 1)

        # show question and get answer
        answer = self._get_answer(ready_question) 

        # check answer with parameters
        parameters = tuple(parameters)
        self._check_answer(answer, *parameters)





class Info:
    def __init__(self, type_members: dict):
        self.types = type_members
        self.typeslist = list(type_members.values())
        self.strtypeslist = Info.list2str(list(type_members))
        
    def list2str(types: list) -> str:
        i = 0
        ret = ''
        tnl = types # list
        for x in tnl:
            ret += '\n\t' + str(i) + '. ' + tnl[i]
            i += 1
        return ret


SEG_INFO = Info(ELF.SEGMENT_TYPES.__members__) # segment types info
SEC_INFO = Info(ELF.SECTION_TYPES.__members__) # section types info
ELF_INFO = Info(ELF.E_TYPE.__members__) # elf types info

# list of questions
qs = []

# number of sections
qs.append(Question('How many sections the file have?', 
                    lambda x: int(x) == Game.binary.header.numberof_sections))
# number of segments
qs.append(Question('How many segments the file have?', 
                    lambda x: int(x) == Game.binary.header.numberof_segments))
# entry point
qs.append(Question('Which virtual address (in hex) OS starts executing after execution?', 
                    lambda x: int(x, 16) == Game.binary.header.entrypoint))
# ELF type
qs.append(Question('What is the type of ELF file?' + ELF_INFO.strtypeslist, 
                    lambda x: ELF_INFO.typeslist[int(x)] == Game.binary.header.file_type))
# 32/64 bit
qs.append(Question('What is the architecture of file 32bit or 64bit? (32/64) ', 
                    lambda x:
                        int(x) == 32 and 
                        Game.binary.header.identity_class == ELF.ELF_CLASS.CLASS32
                        or
                        int(x) == 64 and
                        Game.binary.header.identity_class == ELF.ELF_CLASS.CLASS64))
# segment type
qs.append(DynamicQuestion('What is the type of %&%th segment?' + SEG_INFO.strtypeslist,
                          lambda x, p: Game.binary.segments[p].type == SEG_INFO.typeslist[int(x)],
                          None,
                          lambda: random.randrange(0, Game.binary.header.numberof_segments)))
# section type
qs.append(DynamicQuestion('What is the type of %&%th section?' + SEC_INFO.strtypeslist,
                          lambda x, p: Game.binary.sections[p].type == SEC_INFO.typeslist[int(x)],
                          None,
                          lambda: random.randrange(0, Game.binary.header.numberof_sections)))
#
'''qs.append(DynamicQuestion('Is there %&% section in %&% segment?',
                          lambda x, p: Game.binary.sections[p].type == SEC_INFO.typeslist[int(x)],
                          None,
                          lambda: Game.binary.sections[random.randrange(1, Game.binary.header.numberof_sections)].name,
                          lambda: random.randrange(0, Game.binary.header.numberof_segments)))'''


                          


def ask_a_question():
    global qs
    game = Game()
    Game.questions = qs
    game.ask_random_question()

ask_a_question()
while click.confirm('Do you want to keep playing?', default=True):
    print('\n')
    ask_a_question()
    
if click.confirm('Do you want to delete training folder at last?', default=True):
    shutil.rmtree(args.folder)