from scipy.misc import imresize
from skimage.io import imread
from gym import spaces
import gym
import time
import os
import re
import sys

import numpy as np


class AttentionEnv(gym.Env):
    metadata = {
        "render.modes": ["human", "rgb_array"],
        #"video.frames_per_second" : 2,
    }

    def __init__(self, glimpse_size):
        num_categories = 1000

        data_dir = os.environ.get('IMAGENET_DIR')
        if not data_dir:
            print "Set IMAGENET_DIR env variable"
            sys.exit(1)

        self.glimpse_size = glimpse_size

        self.data = load_data(data_dir)
        np.random.shuffle(self.data)

        self.epochs_complete = 0 

        self.viewer = None

        self.num_steps = 0
        self.index = 0
        self.load_img()
        self.last_action = [0, 0, [0.0, 0.0, 0.0]]

        attention_low = np.array([-1.0, -1.0, 0])
        attention_high = np.array([1.0, 1.0, 1.0])

        attention_space = spaces.Box(attention_low, attention_high)  # (y, x, zoom)

        self.action_space = spaces.Tuple([
            spaces.Discrete(2),  # continue = 0, quit = 1
            spaces.Discrete(num_categories),  # categorization
            attention_space,
        ])

        self.observation_space = spaces.Box(-1.0, 1.0,
                                            (glimpse_size, glimpse_size, 3))

    def translate_attention(self, img_shape):
        #quit = self.last_action[0]
        #classify = self.last_action[1]
        y = self.last_action[2][0]  # [-1, 1]
        x = self.last_action[2][1]  # [-1, 1]
        zoom = self.last_action[2][2]  # [0, 1]

        img_height = img_shape[0]
        img_width = img_shape[1]
        longer_side = max(img_height, img_width)

        center_y = int(y * (longer_side / 2.0) + (img_height / 2.0))
        center_x = int(x * (longer_side / 2.0) + (img_width / 2.0))

        # if zoom == 1, attention_size = glimpse_size
        # if zoom == 0, attention_size = longer_side
        attention_size = zoom * self.glimpse_size + (1 - zoom) * longer_side
        s = attention_size / 2.0

        y_min = int(center_y - s)
        y_max = int(center_y + s)
        x_min = int(center_x - s)
        x_max = int(center_x + s)
        # these values might be negative (meaning the attention streches off the image)
        # or might be larger than the size of the image.. again that the attention stretches off the image.
        return y_min, y_max, x_min, x_max

    def make_observation(self):
        # Output is always glimpse_size x glimpse_size x 3

        # If last_action is at the origin, then zoom 0.0 has the full image
        # contained within the box from [-1, 1] in both height and width.
        # So if we take the longer side of the image.
        img_shape = self.img.shape
        img_height = img_shape[0]
        img_width = img_shape[1]
        assert 3 == img_shape[2], "img should be RGB"

        y_min, y_max, x_min, x_max = self.translate_attention(img_shape)

        pad_top = max(0, -y_min)
        pad_bottom = max(0, y_max - img_height)
        pad_left = max(0, -x_min)
        pad_right = max(0, x_max - img_width)

        y_min = max(0, y_min)
        y_max = min(img_height, y_max)
        x_min = max(0, x_min)
        x_max = min(img_width, x_max)

        crop = self.img[y_min:y_max, x_min:x_max, :]

        pad = ((pad_top, pad_bottom), (pad_left, pad_right), (0, 0))

        padded_crop = np.pad(crop, pad, 'constant', constant_values=0)

        #print "img shape", img_shape
        #print "pad", pad
        #print "crop shape", crop.shape
        #print padded_crop.shape

        #print "mean padded_crop", np.mean(padded_crop)

        observation = imresize(padded_crop,
                               (self.glimpse_size, self.glimpse_size))
        assert observation.shape == (self.glimpse_size, self.glimpse_size, 3)

        #print "mean observation", np.mean(observation)
        observation = observation / 255.0

        return observation



    def _human(self, glimpse):
        human_size = 400
        # This will always return a 400 x 400 image
        # with the current image (self.img) shown in the middle
        # it will draw a red line around the attention box.

        # first draw the image in the middle.
        img_shape = self.img.shape
        img_height = img_shape[0]
        img_width = img_shape[1]
        assert 3 == img_shape[2], "img should be RGB"

        longer_side = max(img_height, img_width)
        shorter_side = min(img_height, img_width)

        scale = float(human_size) / float(longer_side)

        new_shape_shorter = int(shorter_side * scale)
        shorter_padding = human_size - new_shape_shorter

        pad_a = int(shorter_padding / 2)
        pad_b = shorter_padding - pad_a
        if img_height < img_width:
            pad = [[pad_a, pad_b], [0, 0], [0, 0]]
            new_shape = (new_shape_shorter, human_size)
        else:
            pad = [[0, 0], [pad_a, pad_b], [0, 0]]
            new_shape = (human_size, new_shape_shorter)

        # add room at the bottom to display what we're padding to the network:
        bottom_glimpse_padding = 20
        pad[0][1] += bottom_glimpse_padding + self.glimpse_size

        resized = imresize(self.img, new_shape)
        human_img = np.pad(resized, pad, 'constant', constant_values=0)

        # now draw the attention box
        y_min, y_max, x_min, x_max = self.translate_attention((human_size, human_size))

        red = [255.0, 0, 0]

        y_min = max(0, y_min)
        y_max = min(human_size-1, y_max)
        x_min = max(0, x_min)
        x_max = min(human_size-1, x_max)

        human_img[y_min,x_min:x_max,:] = red # top
        human_img[y_max,x_min:x_max,:] = red # bottom
        human_img[y_min:y_max,x_min,:] = red # left
        human_img[y_min:y_max,x_max,:] = red # right


        # Now plce the glimpse at the bottom
        glimpse_y_min = human_size + bottom_glimpse_padding
        glimpse_y_max = glimpse_y_min + self.glimpse_size
        glimpse_x_min = bottom_glimpse_padding 
        glimpse_x_max = bottom_glimpse_padding + self.glimpse_size
        human_img[glimpse_y_min:glimpse_y_max,\
                  glimpse_x_min:glimpse_x_max, :] = glimpse


        return human_img

    def epoch_complete(self):
        self.epochs_complete += 1
        np.random.shuffle(self.data)
        self.index = 0

    def load_img(self):
        if self.index >= len(self.data):
            self.epoch_complete()

        self.current = self.data[self.index]
        img_fn = self.current['filename']

        self.img = imread(img_fn)
        self.img = self.img / 255.0

        if len(self.img.shape) == 2:
            self.img = np.dstack([self.img, self.img, self.img])

        m = np.mean(self.img)
        assert 0.0 <= m and m <= 1.0

    def _reset(self):
        self.num_steps = 0
        self.index += 1
        self.last_action = [0, 0, [0.0, 0.0, 0.0]]
        if self.index > 100000:
            raise NotImplementedError

        self.load_img()

        return self.make_observation()

    def _render(self, mode="human", close=False):
        if close:
            if self.viewer is not None:
                self.viewer.close()
            return

        glimpse = self.make_observation()

        if mode == 'rgb_array':
            return glimpse

        elif mode == 'human':
            from gym.envs.classic_control import rendering
            if self.viewer is None:
                self.viewer = rendering.SimpleImageViewer()
            human_img = self._human(glimpse)
            self.viewer.imshow(human_img)


    def _step(self, action):
        max_steps = 10
        self.num_steps += 1

        done = bool(action[0])
        label_guess = action[1]
        y = action[2][0]
        x = action[2][1]
        zoom = action[2][2]

        self.last_action = action

        reward = 0

        if self.num_steps >= max_steps:
            done = True

        if done:
            #print "guess:", label_guess, synset[label_guess]
            if label_guess == self.current["label_index"]:
                print "CORRECT"
                reward += 1
            else:
                #print "right answer:", self.current["label_index"], self.current["desc"]
                pass

        observation = self.make_observation()
        info = self.current["label_index"]

        return observation, reward, done, info


def file_list(data_dir):
    #import subprocess
    #output = subprocess.check_output(["find", data_dir, "-name", "*.JPEG"])
    #return [s.strip() for s in output.splitlines()]
    dir_txt = data_dir + ".txt"
    filenames = []
    with open(dir_txt, 'r') as f:
        for line in f:
            if line[0] == '.': continue
            line = line.rstrip()
            fn = os.path.join(data_dir, line)
            filenames.append(fn)
    return filenames


def load_data(data_dir):
    data = []
    i = 0

    print "listing files in", data_dir
    start_time = time.time()
    files = file_list(data_dir)
    duration = time.time() - start_time
    print "took %f sec" % duration

    for img_fn in files:
        ext = os.path.splitext(img_fn)[1]
        if ext != '.JPEG': continue

        label_name = re.search(r'(n\d+)', img_fn).group(1)
        fn = os.path.join(data_dir, img_fn)

        label_index = synset_map[label_name]["index"]

        data.append({
            "filename": fn,
            "label_name": label_name,
            "label_index": label_index,
            "desc": synset[label_index],
        })

    return data


synset = [
    "n01440764 tench, Tinca tinca",
    "n01443537 goldfish, Carassius auratus",
    "n01484850 great white shark, white shark, man-eater, man-eating shark, Carcharodon carcharias",
    "n01491361 tiger shark, Galeocerdo cuvieri",
    "n01494475 hammerhead, hammerhead shark",
    "n01496331 electric ray, crampfish, numbfish, torpedo",
    "n01498041 stingray",
    "n01514668 cock",
    "n01514859 hen",
    "n01518878 ostrich, Struthio camelus",
    "n01530575 brambling, Fringilla montifringilla",
    "n01531178 goldfinch, Carduelis carduelis",
    "n01532829 house finch, linnet, Carpodacus mexicanus",
    "n01534433 junco, snowbird",
    "n01537544 indigo bunting, indigo finch, indigo bird, Passerina cyanea",
    "n01558993 robin, American robin, Turdus migratorius",
    "n01560419 bulbul",
    "n01580077 jay",
    "n01582220 magpie",
    "n01592084 chickadee",
    "n01601694 water ouzel, dipper",
    "n01608432 kite",
    "n01614925 bald eagle, American eagle, Haliaeetus leucocephalus",
    "n01616318 vulture",
    "n01622779 great grey owl, great gray owl, Strix nebulosa",
    "n01629819 European fire salamander, Salamandra salamandra",
    "n01630670 common newt, Triturus vulgaris",
    "n01631663 eft",
    "n01632458 spotted salamander, Ambystoma maculatum",
    "n01632777 axolotl, mud puppy, Ambystoma mexicanum",
    "n01641577 bullfrog, Rana catesbeiana",
    "n01644373 tree frog, tree-frog",
    "n01644900 tailed frog, bell toad, ribbed toad, tailed toad, Ascaphus trui",
    "n01664065 loggerhead, loggerhead turtle, Caretta caretta",
    "n01665541 leatherback turtle, leatherback, leathery turtle, Dermochelys coriacea",
    "n01667114 mud turtle",
    "n01667778 terrapin",
    "n01669191 box turtle, box tortoise",
    "n01675722 banded gecko",
    "n01677366 common iguana, iguana, Iguana iguana",
    "n01682714 American chameleon, anole, Anolis carolinensis",
    "n01685808 whiptail, whiptail lizard",
    "n01687978 agama",
    "n01688243 frilled lizard, Chlamydosaurus kingi",
    "n01689811 alligator lizard",
    "n01692333 Gila monster, Heloderma suspectum",
    "n01693334 green lizard, Lacerta viridis",
    "n01694178 African chameleon, Chamaeleo chamaeleon",
    "n01695060 Komodo dragon, Komodo lizard, dragon lizard, giant lizard, Varanus komodoensis",
    "n01697457 African crocodile, Nile crocodile, Crocodylus niloticus",
    "n01698640 American alligator, Alligator mississipiensis",
    "n01704323 triceratops",
    "n01728572 thunder snake, worm snake, Carphophis amoenus",
    "n01728920 ringneck snake, ring-necked snake, ring snake",
    "n01729322 hognose snake, puff adder, sand viper",
    "n01729977 green snake, grass snake",
    "n01734418 king snake, kingsnake",
    "n01735189 garter snake, grass snake",
    "n01737021 water snake",
    "n01739381 vine snake",
    "n01740131 night snake, Hypsiglena torquata",
    "n01742172 boa constrictor, Constrictor constrictor",
    "n01744401 rock python, rock snake, Python sebae",
    "n01748264 Indian cobra, Naja naja",
    "n01749939 green mamba",
    "n01751748 sea snake",
    "n01753488 horned viper, cerastes, sand viper, horned asp, Cerastes cornutus",
    "n01755581 diamondback, diamondback rattlesnake, Crotalus adamanteus",
    "n01756291 sidewinder, horned rattlesnake, Crotalus cerastes",
    "n01768244 trilobite",
    "n01770081 harvestman, daddy longlegs, Phalangium opilio",
    "n01770393 scorpion",
    "n01773157 black and gold garden spider, Argiope aurantia",
    "n01773549 barn spider, Araneus cavaticus",
    "n01773797 garden spider, Aranea diademata",
    "n01774384 black widow, Latrodectus mactans",
    "n01774750 tarantula",
    "n01775062 wolf spider, hunting spider",
    "n01776313 tick",
    "n01784675 centipede",
    "n01795545 black grouse",
    "n01796340 ptarmigan",
    "n01797886 ruffed grouse, partridge, Bonasa umbellus",
    "n01798484 prairie chicken, prairie grouse, prairie fowl",
    "n01806143 peacock",
    "n01806567 quail",
    "n01807496 partridge",
    "n01817953 African grey, African gray, Psittacus erithacus",
    "n01818515 macaw",
    "n01819313 sulphur-crested cockatoo, Kakatoe galerita, Cacatua galerita",
    "n01820546 lorikeet",
    "n01824575 coucal",
    "n01828970 bee eater",
    "n01829413 hornbill",
    "n01833805 hummingbird",
    "n01843065 jacamar",
    "n01843383 toucan",
    "n01847000 drake",
    "n01855032 red-breasted merganser, Mergus serrator",
    "n01855672 goose",
    "n01860187 black swan, Cygnus atratus",
    "n01871265 tusker",
    "n01872401 echidna, spiny anteater, anteater",
    "n01873310 platypus, duckbill, duckbilled platypus, duck-billed platypus, Ornithorhynchus anatinus",
    "n01877812 wallaby, brush kangaroo",
    "n01882714 koala, koala bear, kangaroo bear, native bear, Phascolarctos cinereus",
    "n01883070 wombat",
    "n01910747 jellyfish",
    "n01914609 sea anemone, anemone",
    "n01917289 brain coral",
    "n01924916 flatworm, platyhelminth",
    "n01930112 nematode, nematode worm, roundworm",
    "n01943899 conch",
    "n01944390 snail",
    "n01945685 slug",
    "n01950731 sea slug, nudibranch",
    "n01955084 chiton, coat-of-mail shell, sea cradle, polyplacophore",
    "n01968897 chambered nautilus, pearly nautilus, nautilus",
    "n01978287 Dungeness crab, Cancer magister",
    "n01978455 rock crab, Cancer irroratus",
    "n01980166 fiddler crab",
    "n01981276 king crab, Alaska crab, Alaskan king crab, Alaska king crab, Paralithodes camtschatica",
    "n01983481 American lobster, Northern lobster, Maine lobster, Homarus americanus",
    "n01984695 spiny lobster, langouste, rock lobster, crawfish, crayfish, sea crawfish",
    "n01985128 crayfish, crawfish, crawdad, crawdaddy",
    "n01986214 hermit crab",
    "n01990800 isopod",
    "n02002556 white stork, Ciconia ciconia",
    "n02002724 black stork, Ciconia nigra",
    "n02006656 spoonbill",
    "n02007558 flamingo",
    "n02009229 little blue heron, Egretta caerulea",
    "n02009912 American egret, great white heron, Egretta albus",
    "n02011460 bittern",
    "n02012849 crane",
    "n02013706 limpkin, Aramus pictus",
    "n02017213 European gallinule, Porphyrio porphyrio",
    "n02018207 American coot, marsh hen, mud hen, water hen, Fulica americana",
    "n02018795 bustard",
    "n02025239 ruddy turnstone, Arenaria interpres",
    "n02027492 red-backed sandpiper, dunlin, Erolia alpina",
    "n02028035 redshank, Tringa totanus",
    "n02033041 dowitcher",
    "n02037110 oystercatcher, oyster catcher",
    "n02051845 pelican",
    "n02056570 king penguin, Aptenodytes patagonica",
    "n02058221 albatross, mollymawk",
    "n02066245 grey whale, gray whale, devilfish, Eschrichtius gibbosus, Eschrichtius robustus",
    "n02071294 killer whale, killer, orca, grampus, sea wolf, Orcinus orca",
    "n02074367 dugong, Dugong dugon",
    "n02077923 sea lion",
    "n02085620 Chihuahua",
    "n02085782 Japanese spaniel",
    "n02085936 Maltese dog, Maltese terrier, Maltese",
    "n02086079 Pekinese, Pekingese, Peke",
    "n02086240 Shih-Tzu",
    "n02086646 Blenheim spaniel",
    "n02086910 papillon",
    "n02087046 toy terrier",
    "n02087394 Rhodesian ridgeback",
    "n02088094 Afghan hound, Afghan",
    "n02088238 basset, basset hound",
    "n02088364 beagle",
    "n02088466 bloodhound, sleuthhound",
    "n02088632 bluetick",
    "n02089078 black-and-tan coonhound",
    "n02089867 Walker hound, Walker foxhound",
    "n02089973 English foxhound",
    "n02090379 redbone",
    "n02090622 borzoi, Russian wolfhound",
    "n02090721 Irish wolfhound",
    "n02091032 Italian greyhound",
    "n02091134 whippet",
    "n02091244 Ibizan hound, Ibizan Podenco",
    "n02091467 Norwegian elkhound, elkhound",
    "n02091635 otterhound, otter hound",
    "n02091831 Saluki, gazelle hound",
    "n02092002 Scottish deerhound, deerhound",
    "n02092339 Weimaraner",
    "n02093256 Staffordshire bullterrier, Staffordshire bull terrier",
    "n02093428 American Staffordshire terrier, Staffordshire terrier, American pit bull terrier, pit bull terrier",
    "n02093647 Bedlington terrier",
    "n02093754 Border terrier",
    "n02093859 Kerry blue terrier",
    "n02093991 Irish terrier",
    "n02094114 Norfolk terrier",
    "n02094258 Norwich terrier",
    "n02094433 Yorkshire terrier",
    "n02095314 wire-haired fox terrier",
    "n02095570 Lakeland terrier",
    "n02095889 Sealyham terrier, Sealyham",
    "n02096051 Airedale, Airedale terrier",
    "n02096177 cairn, cairn terrier",
    "n02096294 Australian terrier",
    "n02096437 Dandie Dinmont, Dandie Dinmont terrier",
    "n02096585 Boston bull, Boston terrier",
    "n02097047 miniature schnauzer",
    "n02097130 giant schnauzer",
    "n02097209 standard schnauzer",
    "n02097298 Scotch terrier, Scottish terrier, Scottie",
    "n02097474 Tibetan terrier, chrysanthemum dog",
    "n02097658 silky terrier, Sydney silky",
    "n02098105 soft-coated wheaten terrier",
    "n02098286 West Highland white terrier",
    "n02098413 Lhasa, Lhasa apso",
    "n02099267 flat-coated retriever",
    "n02099429 curly-coated retriever",
    "n02099601 golden retriever",
    "n02099712 Labrador retriever",
    "n02099849 Chesapeake Bay retriever",
    "n02100236 German short-haired pointer",
    "n02100583 vizsla, Hungarian pointer",
    "n02100735 English setter",
    "n02100877 Irish setter, red setter",
    "n02101006 Gordon setter",
    "n02101388 Brittany spaniel",
    "n02101556 clumber, clumber spaniel",
    "n02102040 English springer, English springer spaniel",
    "n02102177 Welsh springer spaniel",
    "n02102318 cocker spaniel, English cocker spaniel, cocker",
    "n02102480 Sussex spaniel",
    "n02102973 Irish water spaniel",
    "n02104029 kuvasz",
    "n02104365 schipperke",
    "n02105056 groenendael",
    "n02105162 malinois",
    "n02105251 briard",
    "n02105412 kelpie",
    "n02105505 komondor",
    "n02105641 Old English sheepdog, bobtail",
    "n02105855 Shetland sheepdog, Shetland sheep dog, Shetland",
    "n02106030 collie",
    "n02106166 Border collie",
    "n02106382 Bouvier des Flandres, Bouviers des Flandres",
    "n02106550 Rottweiler",
    "n02106662 German shepherd, German shepherd dog, German police dog, alsatian",
    "n02107142 Doberman, Doberman pinscher",
    "n02107312 miniature pinscher",
    "n02107574 Greater Swiss Mountain dog",
    "n02107683 Bernese mountain dog",
    "n02107908 Appenzeller",
    "n02108000 EntleBucher",
    "n02108089 boxer",
    "n02108422 bull mastiff",
    "n02108551 Tibetan mastiff",
    "n02108915 French bulldog",
    "n02109047 Great Dane",
    "n02109525 Saint Bernard, St Bernard",
    "n02109961 Eskimo dog, husky",
    "n02110063 malamute, malemute, Alaskan malamute",
    "n02110185 Siberian husky",
    "n02110341 dalmatian, coach dog, carriage dog",
    "n02110627 affenpinscher, monkey pinscher, monkey dog",
    "n02110806 basenji",
    "n02110958 pug, pug-dog",
    "n02111129 Leonberg",
    "n02111277 Newfoundland, Newfoundland dog",
    "n02111500 Great Pyrenees",
    "n02111889 Samoyed, Samoyede",
    "n02112018 Pomeranian",
    "n02112137 chow, chow chow",
    "n02112350 keeshond",
    "n02112706 Brabancon griffon",
    "n02113023 Pembroke, Pembroke Welsh corgi",
    "n02113186 Cardigan, Cardigan Welsh corgi",
    "n02113624 toy poodle",
    "n02113712 miniature poodle",
    "n02113799 standard poodle",
    "n02113978 Mexican hairless",
    "n02114367 timber wolf, grey wolf, gray wolf, Canis lupus",
    "n02114548 white wolf, Arctic wolf, Canis lupus tundrarum",
    "n02114712 red wolf, maned wolf, Canis rufus, Canis niger",
    "n02114855 coyote, prairie wolf, brush wolf, Canis latrans",
    "n02115641 dingo, warrigal, warragal, Canis dingo",
    "n02115913 dhole, Cuon alpinus",
    "n02116738 African hunting dog, hyena dog, Cape hunting dog, Lycaon pictus",
    "n02117135 hyena, hyaena",
    "n02119022 red fox, Vulpes vulpes",
    "n02119789 kit fox, Vulpes macrotis",
    "n02120079 Arctic fox, white fox, Alopex lagopus",
    "n02120505 grey fox, gray fox, Urocyon cinereoargenteus",
    "n02123045 tabby, tabby cat",
    "n02123159 tiger cat",
    "n02123394 Persian cat",
    "n02123597 Siamese cat, Siamese",
    "n02124075 Egyptian cat",
    "n02125311 cougar, puma, catamount, mountain lion, painter, panther, Felis concolor",
    "n02127052 lynx, catamount",
    "n02128385 leopard, Panthera pardus",
    "n02128757 snow leopard, ounce, Panthera uncia",
    "n02128925 jaguar, panther, Panthera onca, Felis onca",
    "n02129165 lion, king of beasts, Panthera leo",
    "n02129604 tiger, Panthera tigris",
    "n02130308 cheetah, chetah, Acinonyx jubatus",
    "n02132136 brown bear, bruin, Ursus arctos",
    "n02133161 American black bear, black bear, Ursus americanus, Euarctos americanus",
    "n02134084 ice bear, polar bear, Ursus Maritimus, Thalarctos maritimus",
    "n02134418 sloth bear, Melursus ursinus, Ursus ursinus",
    "n02137549 mongoose",
    "n02138441 meerkat, mierkat",
    "n02165105 tiger beetle",
    "n02165456 ladybug, ladybeetle, lady beetle, ladybird, ladybird beetle",
    "n02167151 ground beetle, carabid beetle",
    "n02168699 long-horned beetle, longicorn, longicorn beetle",
    "n02169497 leaf beetle, chrysomelid",
    "n02172182 dung beetle",
    "n02174001 rhinoceros beetle",
    "n02177972 weevil",
    "n02190166 fly",
    "n02206856 bee",
    "n02219486 ant, emmet, pismire",
    "n02226429 grasshopper, hopper",
    "n02229544 cricket",
    "n02231487 walking stick, walkingstick, stick insect",
    "n02233338 cockroach, roach",
    "n02236044 mantis, mantid",
    "n02256656 cicada, cicala",
    "n02259212 leafhopper",
    "n02264363 lacewing, lacewing fly",
    "n02268443 dragonfly, darning needle, devil's darning needle, sewing needle, snake feeder, snake doctor, mosquito hawk, skeeter hawk",
    "n02268853 damselfly",
    "n02276258 admiral",
    "n02277742 ringlet, ringlet butterfly",
    "n02279972 monarch, monarch butterfly, milkweed butterfly, Danaus plexippus",
    "n02280649 cabbage butterfly",
    "n02281406 sulphur butterfly, sulfur butterfly",
    "n02281787 lycaenid, lycaenid butterfly",
    "n02317335 starfish, sea star",
    "n02319095 sea urchin",
    "n02321529 sea cucumber, holothurian",
    "n02325366 wood rabbit, cottontail, cottontail rabbit",
    "n02326432 hare",
    "n02328150 Angora, Angora rabbit",
    "n02342885 hamster",
    "n02346627 porcupine, hedgehog",
    "n02356798 fox squirrel, eastern fox squirrel, Sciurus niger",
    "n02361337 marmot",
    "n02363005 beaver",
    "n02364673 guinea pig, Cavia cobaya",
    "n02389026 sorrel",
    "n02391049 zebra",
    "n02395406 hog, pig, grunter, squealer, Sus scrofa",
    "n02396427 wild boar, boar, Sus scrofa",
    "n02397096 warthog",
    "n02398521 hippopotamus, hippo, river horse, Hippopotamus amphibius",
    "n02403003 ox",
    "n02408429 water buffalo, water ox, Asiatic buffalo, Bubalus bubalis",
    "n02410509 bison",
    "n02412080 ram, tup",
    "n02415577 bighorn, bighorn sheep, cimarron, Rocky Mountain bighorn, Rocky Mountain sheep, Ovis canadensis",
    "n02417914 ibex, Capra ibex",
    "n02422106 hartebeest",
    "n02422699 impala, Aepyceros melampus",
    "n02423022 gazelle",
    "n02437312 Arabian camel, dromedary, Camelus dromedarius",
    "n02437616 llama",
    "n02441942 weasel",
    "n02442845 mink",
    "n02443114 polecat, fitch, foulmart, foumart, Mustela putorius",
    "n02443484 black-footed ferret, ferret, Mustela nigripes",
    "n02444819 otter",
    "n02445715 skunk, polecat, wood pussy",
    "n02447366 badger",
    "n02454379 armadillo",
    "n02457408 three-toed sloth, ai, Bradypus tridactylus",
    "n02480495 orangutan, orang, orangutang, Pongo pygmaeus",
    "n02480855 gorilla, Gorilla gorilla",
    "n02481823 chimpanzee, chimp, Pan troglodytes",
    "n02483362 gibbon, Hylobates lar",
    "n02483708 siamang, Hylobates syndactylus, Symphalangus syndactylus",
    "n02484975 guenon, guenon monkey",
    "n02486261 patas, hussar monkey, Erythrocebus patas",
    "n02486410 baboon",
    "n02487347 macaque",
    "n02488291 langur",
    "n02488702 colobus, colobus monkey",
    "n02489166 proboscis monkey, Nasalis larvatus",
    "n02490219 marmoset",
    "n02492035 capuchin, ringtail, Cebus capucinus",
    "n02492660 howler monkey, howler",
    "n02493509 titi, titi monkey",
    "n02493793 spider monkey, Ateles geoffroyi",
    "n02494079 squirrel monkey, Saimiri sciureus",
    "n02497673 Madagascar cat, ring-tailed lemur, Lemur catta",
    "n02500267 indri, indris, Indri indri, Indri brevicaudatus",
    "n02504013 Indian elephant, Elephas maximus",
    "n02504458 African elephant, Loxodonta africana",
    "n02509815 lesser panda, red panda, panda, bear cat, cat bear, Ailurus fulgens",
    "n02510455 giant panda, panda, panda bear, coon bear, Ailuropoda melanoleuca",
    "n02514041 barracouta, snoek",
    "n02526121 eel",
    "n02536864 coho, cohoe, coho salmon, blue jack, silver salmon, Oncorhynchus kisutch",
    "n02606052 rock beauty, Holocanthus tricolor",
    "n02607072 anemone fish",
    "n02640242 sturgeon",
    "n02641379 gar, garfish, garpike, billfish, Lepisosteus osseus",
    "n02643566 lionfish",
    "n02655020 puffer, pufferfish, blowfish, globefish",
    "n02666196 abacus",
    "n02667093 abaya",
    "n02669723 academic gown, academic robe, judge's robe",
    "n02672831 accordion, piano accordion, squeeze box",
    "n02676566 acoustic guitar",
    "n02687172 aircraft carrier, carrier, flattop, attack aircraft carrier",
    "n02690373 airliner",
    "n02692877 airship, dirigible",
    "n02699494 altar",
    "n02701002 ambulance",
    "n02704792 amphibian, amphibious vehicle",
    "n02708093 analog clock",
    "n02727426 apiary, bee house",
    "n02730930 apron",
    "n02747177 ashcan, trash can, garbage can, wastebin, ash bin, ash-bin, ashbin, dustbin, trash barrel, trash bin",
    "n02749479 assault rifle, assault gun",
    "n02769748 backpack, back pack, knapsack, packsack, rucksack, haversack",
    "n02776631 bakery, bakeshop, bakehouse",
    "n02777292 balance beam, beam",
    "n02782093 balloon",
    "n02783161 ballpoint, ballpoint pen, ballpen, Biro",
    "n02786058 Band Aid",
    "n02787622 banjo",
    "n02788148 bannister, banister, balustrade, balusters, handrail",
    "n02790996 barbell",
    "n02791124 barber chair",
    "n02791270 barbershop",
    "n02793495 barn",
    "n02794156 barometer",
    "n02795169 barrel, cask",
    "n02797295 barrow, garden cart, lawn cart, wheelbarrow",
    "n02799071 baseball",
    "n02802426 basketball",
    "n02804414 bassinet",
    "n02804610 bassoon",
    "n02807133 bathing cap, swimming cap",
    "n02808304 bath towel",
    "n02808440 bathtub, bathing tub, bath, tub",
    "n02814533 beach wagon, station wagon, wagon, estate car, beach waggon, station waggon, waggon",
    "n02814860 beacon, lighthouse, beacon light, pharos",
    "n02815834 beaker",
    "n02817516 bearskin, busby, shako",
    "n02823428 beer bottle",
    "n02823750 beer glass",
    "n02825657 bell cote, bell cot",
    "n02834397 bib",
    "n02835271 bicycle-built-for-two, tandem bicycle, tandem",
    "n02837789 bikini, two-piece",
    "n02840245 binder, ring-binder",
    "n02841315 binoculars, field glasses, opera glasses",
    "n02843684 birdhouse",
    "n02859443 boathouse",
    "n02860847 bobsled, bobsleigh, bob",
    "n02865351 bolo tie, bolo, bola tie, bola",
    "n02869837 bonnet, poke bonnet",
    "n02870880 bookcase",
    "n02871525 bookshop, bookstore, bookstall",
    "n02877765 bottlecap",
    "n02879718 bow",
    "n02883205 bow tie, bow-tie, bowtie",
    "n02892201 brass, memorial tablet, plaque",
    "n02892767 brassiere, bra, bandeau",
    "n02894605 breakwater, groin, groyne, mole, bulwark, seawall, jetty",
    "n02895154 breastplate, aegis, egis",
    "n02906734 broom",
    "n02909870 bucket, pail",
    "n02910353 buckle",
    "n02916936 bulletproof vest",
    "n02917067 bullet train, bullet",
    "n02927161 butcher shop, meat market",
    "n02930766 cab, hack, taxi, taxicab",
    "n02939185 caldron, cauldron",
    "n02948072 candle, taper, wax light",
    "n02950826 cannon",
    "n02951358 canoe",
    "n02951585 can opener, tin opener",
    "n02963159 cardigan",
    "n02965783 car mirror",
    "n02966193 carousel, carrousel, merry-go-round, roundabout, whirligig",
    "n02966687 carpenter's kit, tool kit",
    "n02971356 carton",
    "n02974003 car wheel",
    "n02977058 cash machine, cash dispenser, automated teller machine, automatic teller machine, automated teller, automatic teller, ATM",
    "n02978881 cassette",
    "n02979186 cassette player",
    "n02980441 castle",
    "n02981792 catamaran",
    "n02988304 CD player",
    "n02992211 cello, violoncello",
    "n02992529 cellular telephone, cellular phone, cellphone, cell, mobile phone",
    "n02999410 chain",
    "n03000134 chainlink fence",
    "n03000247 chain mail, ring mail, mail, chain armor, chain armour, ring armor, ring armour",
    "n03000684 chain saw, chainsaw",
    "n03014705 chest",
    "n03016953 chiffonier, commode",
    "n03017168 chime, bell, gong",
    "n03018349 china cabinet, china closet",
    "n03026506 Christmas stocking",
    "n03028079 church, church building",
    "n03032252 cinema, movie theater, movie theatre, movie house, picture palace",
    "n03041632 cleaver, meat cleaver, chopper",
    "n03042490 cliff dwelling",
    "n03045698 cloak",
    "n03047690 clog, geta, patten, sabot",
    "n03062245 cocktail shaker",
    "n03063599 coffee mug",
    "n03063689 coffeepot",
    "n03065424 coil, spiral, volute, whorl, helix",
    "n03075370 combination lock",
    "n03085013 computer keyboard, keypad",
    "n03089624 confectionery, confectionary, candy store",
    "n03095699 container ship, containership, container vessel",
    "n03100240 convertible",
    "n03109150 corkscrew, bottle screw",
    "n03110669 cornet, horn, trumpet, trump",
    "n03124043 cowboy boot",
    "n03124170 cowboy hat, ten-gallon hat",
    "n03125729 cradle",
    "n03126707 crane",
    "n03127747 crash helmet",
    "n03127925 crate",
    "n03131574 crib, cot",
    "n03133878 Crock Pot",
    "n03134739 croquet ball",
    "n03141823 crutch",
    "n03146219 cuirass",
    "n03160309 dam, dike, dyke",
    "n03179701 desk",
    "n03180011 desktop computer",
    "n03187595 dial telephone, dial phone",
    "n03188531 diaper, nappy, napkin",
    "n03196217 digital clock",
    "n03197337 digital watch",
    "n03201208 dining table, board",
    "n03207743 dishrag, dishcloth",
    "n03207941 dishwasher, dish washer, dishwashing machine",
    "n03208938 disk brake, disc brake",
    "n03216828 dock, dockage, docking facility",
    "n03218198 dogsled, dog sled, dog sleigh",
    "n03220513 dome",
    "n03223299 doormat, welcome mat",
    "n03240683 drilling platform, offshore rig",
    "n03249569 drum, membranophone, tympan",
    "n03250847 drumstick",
    "n03255030 dumbbell",
    "n03259280 Dutch oven",
    "n03271574 electric fan, blower",
    "n03272010 electric guitar",
    "n03272562 electric locomotive",
    "n03290653 entertainment center",
    "n03291819 envelope",
    "n03297495 espresso maker",
    "n03314780 face powder",
    "n03325584 feather boa, boa",
    "n03337140 file, file cabinet, filing cabinet",
    "n03344393 fireboat",
    "n03345487 fire engine, fire truck",
    "n03347037 fire screen, fireguard",
    "n03355925 flagpole, flagstaff",
    "n03372029 flute, transverse flute",
    "n03376595 folding chair",
    "n03379051 football helmet",
    "n03384352 forklift",
    "n03388043 fountain",
    "n03388183 fountain pen",
    "n03388549 four-poster",
    "n03393912 freight car",
    "n03394916 French horn, horn",
    "n03400231 frying pan, frypan, skillet",
    "n03404251 fur coat",
    "n03417042 garbage truck, dustcart",
    "n03424325 gasmask, respirator, gas helmet",
    "n03425413 gas pump, gasoline pump, petrol pump, island dispenser",
    "n03443371 goblet",
    "n03444034 go-kart",
    "n03445777 golf ball",
    "n03445924 golfcart, golf cart",
    "n03447447 gondola",
    "n03447721 gong, tam-tam",
    "n03450230 gown",
    "n03452741 grand piano, grand",
    "n03457902 greenhouse, nursery, glasshouse",
    "n03459775 grille, radiator grille",
    "n03461385 grocery store, grocery, food market, market",
    "n03467068 guillotine",
    "n03476684 hair slide",
    "n03476991 hair spray",
    "n03478589 half track",
    "n03481172 hammer",
    "n03482405 hamper",
    "n03483316 hand blower, blow dryer, blow drier, hair dryer, hair drier",
    "n03485407 hand-held computer, hand-held microcomputer",
    "n03485794 handkerchief, hankie, hanky, hankey",
    "n03492542 hard disc, hard disk, fixed disk",
    "n03494278 harmonica, mouth organ, harp, mouth harp",
    "n03495258 harp",
    "n03496892 harvester, reaper",
    "n03498962 hatchet",
    "n03527444 holster",
    "n03529860 home theater, home theatre",
    "n03530642 honeycomb",
    "n03532672 hook, claw",
    "n03534580 hoopskirt, crinoline",
    "n03535780 horizontal bar, high bar",
    "n03538406 horse cart, horse-cart",
    "n03544143 hourglass",
    "n03584254 iPod",
    "n03584829 iron, smoothing iron",
    "n03590841 jack-o'-lantern",
    "n03594734 jean, blue jean, denim",
    "n03594945 jeep, landrover",
    "n03595614 jersey, T-shirt, tee shirt",
    "n03598930 jigsaw puzzle",
    "n03599486 jinrikisha, ricksha, rickshaw",
    "n03602883 joystick",
    "n03617480 kimono",
    "n03623198 knee pad",
    "n03627232 knot",
    "n03630383 lab coat, laboratory coat",
    "n03633091 ladle",
    "n03637318 lampshade, lamp shade",
    "n03642806 laptop, laptop computer",
    "n03649909 lawn mower, mower",
    "n03657121 lens cap, lens cover",
    "n03658185 letter opener, paper knife, paperknife",
    "n03661043 library",
    "n03662601 lifeboat",
    "n03666591 lighter, light, igniter, ignitor",
    "n03670208 limousine, limo",
    "n03673027 liner, ocean liner",
    "n03676483 lipstick, lip rouge",
    "n03680355 Loafer",
    "n03690938 lotion",
    "n03691459 loudspeaker, speaker, speaker unit, loudspeaker system, speaker system",
    "n03692522 loupe, jeweler's loupe",
    "n03697007 lumbermill, sawmill",
    "n03706229 magnetic compass",
    "n03709823 mailbag, postbag",
    "n03710193 mailbox, letter box",
    "n03710637 maillot",
    "n03710721 maillot, tank suit",
    "n03717622 manhole cover",
    "n03720891 maraca",
    "n03721384 marimba, xylophone",
    "n03724870 mask",
    "n03729826 matchstick",
    "n03733131 maypole",
    "n03733281 maze, labyrinth",
    "n03733805 measuring cup",
    "n03742115 medicine chest, medicine cabinet",
    "n03743016 megalith, megalithic structure",
    "n03759954 microphone, mike",
    "n03761084 microwave, microwave oven",
    "n03763968 military uniform",
    "n03764736 milk can",
    "n03769881 minibus",
    "n03770439 miniskirt, mini",
    "n03770679 minivan",
    "n03773504 missile",
    "n03775071 mitten",
    "n03775546 mixing bowl",
    "n03776460 mobile home, manufactured home",
    "n03777568 Model T",
    "n03777754 modem",
    "n03781244 monastery",
    "n03782006 monitor",
    "n03785016 moped",
    "n03786901 mortar",
    "n03787032 mortarboard",
    "n03788195 mosque",
    "n03788365 mosquito net",
    "n03791053 motor scooter, scooter",
    "n03792782 mountain bike, all-terrain bike, off-roader",
    "n03792972 mountain tent",
    "n03793489 mouse, computer mouse",
    "n03794056 mousetrap",
    "n03796401 moving van",
    "n03803284 muzzle",
    "n03804744 nail",
    "n03814639 neck brace",
    "n03814906 necklace",
    "n03825788 nipple",
    "n03832673 notebook, notebook computer",
    "n03837869 obelisk",
    "n03838899 oboe, hautboy, hautbois",
    "n03840681 ocarina, sweet potato",
    "n03841143 odometer, hodometer, mileometer, milometer",
    "n03843555 oil filter",
    "n03854065 organ, pipe organ",
    "n03857828 oscilloscope, scope, cathode-ray oscilloscope, CRO",
    "n03866082 overskirt",
    "n03868242 oxcart",
    "n03868863 oxygen mask",
    "n03871628 packet",
    "n03873416 paddle, boat paddle",
    "n03874293 paddlewheel, paddle wheel",
    "n03874599 padlock",
    "n03876231 paintbrush",
    "n03877472 pajama, pyjama, pj's, jammies",
    "n03877845 palace",
    "n03884397 panpipe, pandean pipe, syrinx",
    "n03887697 paper towel",
    "n03888257 parachute, chute",
    "n03888605 parallel bars, bars",
    "n03891251 park bench",
    "n03891332 parking meter",
    "n03895866 passenger car, coach, carriage",
    "n03899768 patio, terrace",
    "n03902125 pay-phone, pay-station",
    "n03903868 pedestal, plinth, footstall",
    "n03908618 pencil box, pencil case",
    "n03908714 pencil sharpener",
    "n03916031 perfume, essence",
    "n03920288 Petri dish",
    "n03924679 photocopier",
    "n03929660 pick, plectrum, plectron",
    "n03929855 pickelhaube",
    "n03930313 picket fence, paling",
    "n03930630 pickup, pickup truck",
    "n03933933 pier",
    "n03935335 piggy bank, penny bank",
    "n03937543 pill bottle",
    "n03938244 pillow",
    "n03942813 ping-pong ball",
    "n03944341 pinwheel",
    "n03947888 pirate, pirate ship",
    "n03950228 pitcher, ewer",
    "n03954731 plane, carpenter's plane, woodworking plane",
    "n03956157 planetarium",
    "n03958227 plastic bag",
    "n03961711 plate rack",
    "n03967562 plow, plough",
    "n03970156 plunger, plumber's helper",
    "n03976467 Polaroid camera, Polaroid Land camera",
    "n03976657 pole",
    "n03977966 police van, police wagon, paddy wagon, patrol wagon, wagon, black Maria",
    "n03980874 poncho",
    "n03982430 pool table, billiard table, snooker table",
    "n03983396 pop bottle, soda bottle",
    "n03991062 pot, flowerpot",
    "n03992509 potter's wheel",
    "n03995372 power drill",
    "n03998194 prayer rug, prayer mat",
    "n04004767 printer",
    "n04005630 prison, prison house",
    "n04008634 projectile, missile",
    "n04009552 projector",
    "n04019541 puck, hockey puck",
    "n04023962 punching bag, punch bag, punching ball, punchball",
    "n04026417 purse",
    "n04033901 quill, quill pen",
    "n04033995 quilt, comforter, comfort, puff",
    "n04037443 racer, race car, racing car",
    "n04039381 racket, racquet",
    "n04040759 radiator",
    "n04041544 radio, wireless",
    "n04044716 radio telescope, radio reflector",
    "n04049303 rain barrel",
    "n04065272 recreational vehicle, RV, R.V.",
    "n04067472 reel",
    "n04069434 reflex camera",
    "n04070727 refrigerator, icebox",
    "n04074963 remote control, remote",
    "n04081281 restaurant, eating house, eating place, eatery",
    "n04086273 revolver, six-gun, six-shooter",
    "n04090263 rifle",
    "n04099969 rocking chair, rocker",
    "n04111531 rotisserie",
    "n04116512 rubber eraser, rubber, pencil eraser",
    "n04118538 rugby ball",
    "n04118776 rule, ruler",
    "n04120489 running shoe",
    "n04125021 safe",
    "n04127249 safety pin",
    "n04131690 saltshaker, salt shaker",
    "n04133789 sandal",
    "n04136333 sarong",
    "n04141076 sax, saxophone",
    "n04141327 scabbard",
    "n04141975 scale, weighing machine",
    "n04146614 school bus",
    "n04147183 schooner",
    "n04149813 scoreboard",
    "n04152593 screen, CRT screen",
    "n04153751 screw",
    "n04154565 screwdriver",
    "n04162706 seat belt, seatbelt",
    "n04179913 sewing machine",
    "n04192698 shield, buckler",
    "n04200800 shoe shop, shoe-shop, shoe store",
    "n04201297 shoji",
    "n04204238 shopping basket",
    "n04204347 shopping cart",
    "n04208210 shovel",
    "n04209133 shower cap",
    "n04209239 shower curtain",
    "n04228054 ski",
    "n04229816 ski mask",
    "n04235860 sleeping bag",
    "n04238763 slide rule, slipstick",
    "n04239074 sliding door",
    "n04243546 slot, one-armed bandit",
    "n04251144 snorkel",
    "n04252077 snowmobile",
    "n04252225 snowplow, snowplough",
    "n04254120 soap dispenser",
    "n04254680 soccer ball",
    "n04254777 sock",
    "n04258138 solar dish, solar collector, solar furnace",
    "n04259630 sombrero",
    "n04263257 soup bowl",
    "n04264628 space bar",
    "n04265275 space heater",
    "n04266014 space shuttle",
    "n04270147 spatula",
    "n04273569 speedboat",
    "n04275548 spider web, spider's web",
    "n04277352 spindle",
    "n04285008 sports car, sport car",
    "n04286575 spotlight, spot",
    "n04296562 stage",
    "n04310018 steam locomotive",
    "n04311004 steel arch bridge",
    "n04311174 steel drum",
    "n04317175 stethoscope",
    "n04325704 stole",
    "n04326547 stone wall",
    "n04328186 stopwatch, stop watch",
    "n04330267 stove",
    "n04332243 strainer",
    "n04335435 streetcar, tram, tramcar, trolley, trolley car",
    "n04336792 stretcher",
    "n04344873 studio couch, day bed",
    "n04346328 stupa, tope",
    "n04347754 submarine, pigboat, sub, U-boat",
    "n04350905 suit, suit of clothes",
    "n04355338 sundial",
    "n04355933 sunglass",
    "n04356056 sunglasses, dark glasses, shades",
    "n04357314 sunscreen, sunblock, sun blocker",
    "n04366367 suspension bridge",
    "n04367480 swab, swob, mop",
    "n04370456 sweatshirt",
    "n04371430 swimming trunks, bathing trunks",
    "n04371774 swing",
    "n04372370 switch, electric switch, electrical switch",
    "n04376876 syringe",
    "n04380533 table lamp",
    "n04389033 tank, army tank, armored combat vehicle, armoured combat vehicle",
    "n04392985 tape player",
    "n04398044 teapot",
    "n04399382 teddy, teddy bear",
    "n04404412 television, television system",
    "n04409515 tennis ball",
    "n04417672 thatch, thatched roof",
    "n04418357 theater curtain, theatre curtain",
    "n04423845 thimble",
    "n04428191 thresher, thrasher, threshing machine",
    "n04429376 throne",
    "n04435653 tile roof",
    "n04442312 toaster",
    "n04443257 tobacco shop, tobacconist shop, tobacconist",
    "n04447861 toilet seat",
    "n04456115 torch",
    "n04458633 totem pole",
    "n04461696 tow truck, tow car, wrecker",
    "n04462240 toyshop",
    "n04465501 tractor",
    "n04467665 trailer truck, tractor trailer, trucking rig, rig, articulated lorry, semi",
    "n04476259 tray",
    "n04479046 trench coat",
    "n04482393 tricycle, trike, velocipede",
    "n04483307 trimaran",
    "n04485082 tripod",
    "n04486054 triumphal arch",
    "n04487081 trolleybus, trolley coach, trackless trolley",
    "n04487394 trombone",
    "n04493381 tub, vat",
    "n04501370 turnstile",
    "n04505470 typewriter keyboard",
    "n04507155 umbrella",
    "n04509417 unicycle, monocycle",
    "n04515003 upright, upright piano",
    "n04517823 vacuum, vacuum cleaner",
    "n04522168 vase",
    "n04523525 vault",
    "n04525038 velvet",
    "n04525305 vending machine",
    "n04532106 vestment",
    "n04532670 viaduct",
    "n04536866 violin, fiddle",
    "n04540053 volleyball",
    "n04542943 waffle iron",
    "n04548280 wall clock",
    "n04548362 wallet, billfold, notecase, pocketbook",
    "n04550184 wardrobe, closet, press",
    "n04552348 warplane, military plane",
    "n04553703 washbasin, handbasin, washbowl, lavabo, wash-hand basin",
    "n04554684 washer, automatic washer, washing machine",
    "n04557648 water bottle",
    "n04560804 water jug",
    "n04562935 water tower",
    "n04579145 whiskey jug",
    "n04579432 whistle",
    "n04584207 wig",
    "n04589890 window screen",
    "n04590129 window shade",
    "n04591157 Windsor tie",
    "n04591713 wine bottle",
    "n04592741 wing",
    "n04596742 wok",
    "n04597913 wooden spoon",
    "n04599235 wool, woolen, woollen",
    "n04604644 worm fence, snake fence, snake-rail fence, Virginia fence",
    "n04606251 wreck",
    "n04612504 yawl",
    "n04613696 yurt",
    "n06359193 web site, website, internet site, site",
    "n06596364 comic book",
    "n06785654 crossword puzzle, crossword",
    "n06794110 street sign",
    "n06874185 traffic light, traffic signal, stoplight",
    "n07248320 book jacket, dust cover, dust jacket, dust wrapper",
    "n07565083 menu",
    "n07579787 plate",
    "n07583066 guacamole",
    "n07584110 consomme",
    "n07590611 hot pot, hotpot",
    "n07613480 trifle",
    "n07614500 ice cream, icecream",
    "n07615774 ice lolly, lolly, lollipop, popsicle",
    "n07684084 French loaf",
    "n07693725 bagel, beigel",
    "n07695742 pretzel",
    "n07697313 cheeseburger",
    "n07697537 hotdog, hot dog, red hot",
    "n07711569 mashed potato",
    "n07714571 head cabbage",
    "n07714990 broccoli",
    "n07715103 cauliflower",
    "n07716358 zucchini, courgette",
    "n07716906 spaghetti squash",
    "n07717410 acorn squash",
    "n07717556 butternut squash",
    "n07718472 cucumber, cuke",
    "n07718747 artichoke, globe artichoke",
    "n07720875 bell pepper",
    "n07730033 cardoon",
    "n07734744 mushroom",
    "n07742313 Granny Smith",
    "n07745940 strawberry",
    "n07747607 orange",
    "n07749582 lemon",
    "n07753113 fig",
    "n07753275 pineapple, ananas",
    "n07753592 banana",
    "n07754684 jackfruit, jak, jack",
    "n07760859 custard apple",
    "n07768694 pomegranate",
    "n07802026 hay",
    "n07831146 carbonara",
    "n07836838 chocolate sauce, chocolate syrup",
    "n07860988 dough",
    "n07871810 meat loaf, meatloaf",
    "n07873807 pizza, pizza pie",
    "n07875152 potpie",
    "n07880968 burrito",
    "n07892512 red wine",
    "n07920052 espresso",
    "n07930864 cup",
    "n07932039 eggnog",
    "n09193705 alp",
    "n09229709 bubble",
    "n09246464 cliff, drop, drop-off",
    "n09256479 coral reef",
    "n09288635 geyser",
    "n09332890 lakeside, lakeshore",
    "n09399592 promontory, headland, head, foreland",
    "n09421951 sandbar, sand bar",
    "n09428293 seashore, coast, seacoast, sea-coast",
    "n09468604 valley, vale",
    "n09472597 volcano",
    "n09835506 ballplayer, baseball player",
    "n10148035 groom, bridegroom",
    "n10565667 scuba diver",
    "n11879895 rapeseed",
    "n11939491 daisy",
    "n12057211 yellow lady's slipper, yellow lady-slipper, Cypripedium calceolus, Cypripedium parviflorum",
    "n12144580 corn",
    "n12267677 acorn",
    "n12620546 hip, rose hip, rosehip",
    "n12768682 buckeye, horse chestnut, conker",
    "n12985857 coral fungus",
    "n12998815 agaric",
    "n13037406 gyromitra",
    "n13040303 stinkhorn, carrion fungus",
    "n13044778 earthstar",
    "n13052670 hen-of-the-woods, hen of the woods, Polyporus frondosus, Grifola frondosa",
    "n13054560 bolete",
    "n13133613 ear, spike, capitulum",
    "n15075141 toilet tissue, toilet paper, bathroom tissue",
]

synset_map = {}
for i, l in enumerate(synset):
    label, desc = l.split(' ', 1)
    synset_map[label] = {"index": i, "desc": desc, }
