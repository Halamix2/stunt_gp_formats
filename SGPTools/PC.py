#!/usr/bin/python3 
# coding=utf-8

import os
import sys

# files
import pathlib

from PIL import Image # type: ignore

# binary
import struct

#TODO check if size is at least 1x1
class PC():
    def __init__(self):
        self.__magic = b'TM!\x1A'
        self.__unknown = b'\x03\x00'
        self.__width = 0
        self.__height = 0
        self.__data = b''
    
    @classmethod
    def from_pc(cls, filename: str):
        new_pc = cls()
        with open(filename, 'rb') as pc_file:
            new_pc.__magic = pc_file.read(4)
            if new_pc.__magic != b'TM!\x1a':
                return None
            new_pc.__unknown = pc_file.read(2)
            new_pc.__width = struct.unpack("<H",pc_file.read(2))[0]
            new_pc.__height = struct.unpack("<H",pc_file.read(2))[0]
            
            new_pc.__data = new_pc.__unpack(pc_file.read(), new_pc.__width, new_pc.__height)
            
        if new_pc.check():
            return new_pc
    
    @classmethod
    def from_png(cls, filename: str):
        new_pc = cls()
        image = Image.open(filename).convert("RGBA")
        new_pc.__width = image.width
        new_pc.__height = image.height

        pixels = list(image.getdata())
        data = [b'\x00\x00'] * new_pc.__width * new_pc.__height
        i = 0
        for r, g, b, alpha in pixels:
            pixel_16 = 0

            # one byte alpha
            alpha = round(alpha >= 128)
            pixel_16 += alpha << 15

            # convert 0-255 to 0-31
            r = round(31*(r/255))
            pixel_16 += r << 10

            g = round(31*(g/255))
            pixel_16 += g << 5

            b = round(31*(b/255))
            pixel_16 += b

            data[i] = pixel_16.to_bytes(2, 'little')
            i += 1

        new_pc.__data = b''.join(data)

        if len(new_pc.__data) == 0:
            raise Exception('PC data cannot be empty!')
        return new_pc
   
    
    def to_pc(self, filename: str, compress = True):
        with open(filename, 'wb') as pc_file:
            pc_file.write(self.__magic)
            pc_file.write(self.__unknown)
            pc_file.write(self.__width.to_bytes(2, 'little'))
            pc_file.write(self.__height.to_bytes(2, 'little'))
            #pc_file.write(packed)
            self.__pack(pc_file, compress)
        pass
    
    def to_png(self, filename: str):
        print('saving to', filename)
        image = Image.new('RGBA', (self.__width, self.__height))
        #Image.new('RGBA', (data['width'], data['height']))
        image.putdata(self.__convert_colours(self.__data, self.__width, self.__height))
        image.save(filename, 'PNG')
    
    def check(self) -> bool:
    
        try:
            assert self.__magic == b'TM!\x1A', 'wrong magic'

            assert self.__width > 0, 'width <= 0'
            assert self.__width <= 65536, 'width > 65536'

            assert self.__height > 0, 'height <= 0'
            assert self.__height <= 65536, 'height > 65536'

        except AssertionError as error:
            print('assertion error:', error)
            return False
        
        try:
            assert self.__unknown == b'\x03\x00', 'wrong unknown'
        except AssertionError as error:
            print('assertion suggestion:', error)
        
        return True
    
    def __unpack(self, packed_data: bytes, width: int, height: int):
        unpacked_data = [b'\x00\x00'] * width * height
        p = 0
        u = 0
        
        # as everything, read data by 2 bytes
        packed_data = memoryview(packed_data).cast('H')
        current_word = packed_data[p]
        
        #copy first pixel to output
        unpacked_data[0] = current_word.to_bytes(2, 'little')
        p += 1
        u += 1 # unpacked
        while True:
            current_word = packed_data[p]
            
            # just stream pixels while 15th bit set.
            # It is also used for alpha channel, so we know for a fact that these pixels are opaque
            while (current_word >> 15) & 1 == 1:
                p = p + 1
                unpacked_data[u] = current_word.to_bytes(2, 'little')
                u += 1
                current_word = packed_data[p]
            
            p = p + 1
            
            # is 14th bit set
            if (current_word >> 14) & 1 == 1:
                repeats = ((current_word>>11) & 7) + 1
                location = current_word & 0x7FF
                head = u - 1
                
                for j in range(repeats+1):
                    #repeat two bytes from output
                    unpacked_data[u] = unpacked_data[head - location + j]
                    u += 1

            else:
                # get 13 bits from last pixel
                current_word = (current_word & 0x3FFF) * 4

                if current_word == 0:
                    break

                fill = (current_word ) & 3
                current_word = current_word >> 2

                for j in range(current_word):
                    unpacked_data[u] + b'\x00\x00'
                    u += 1

                if fill == 2:
                    unpacked_data[u] + b'\x00\x00'
                    u += 1
    
        return b''.join(unpacked_data)
        
    # TODO fix
    def __pack(self, f, compress = False):
        pixels_t = memoryview(self.__data).cast('H')
        pixels = [i for i in pixels_t]
        #1st pixel is passed as-is
        f.write(pixels[0].to_bytes(2, "little"))

        # skip 1st pixel
        u = 1
        # TODO add some abstraction, this is ugly!
        length = len(pixels)
        while u < length:
            # check if pixlex is trasparent (15th bit is unset)
            if pixels[u] < 0x8000:
                count = 1
                # it should split after 16384 pixels
                # TODO coult all pixels at once and then cut?
                # Yeah, I could do that but there are bigger time loses with non-transparent pixels
                while u + count + 1 < length and pixels[u + count] == 0 and count < 16383:
                    count += 1
                f.write(count.to_bytes(2, "little"))
                u += count

            # non-transparent pixels        
            else:
                if compress:
                    # count repeating pixels
                    # location can be max 2^11 -1 = 2047
                    # count can be between 2-10
                    count = 0
                    location = 0

                    j = min(u, 2048)
                    while j > 0: 
                        current_count = 0
                        while u + 1 + current_count < length and pixels[u - j + current_count] == pixels[u + current_count]:
                            current_count += 1
                        
                        if current_count > count:
                            count = current_count
                            location = j
                            if count >= 9:
                                break
                        j -= current_count + 1

                    if count > 1: #it's only viable for more than 1 pixel
                        #pack data
                        while count > 1:
                            currently_counted = min(9, count)
                            package = 0b0100000000000000 | ((currently_counted-2) << 11) | (location-1)
                            f.write(package.to_bytes(2, "little"))
                            u += currently_counted
                            count -= currently_counted
                    else:
                        # stream data
                        f.write(pixels[u].to_bytes(2, "little"))
                        u += 1
                else:
                    # stream data
                    f.write(pixels[u].to_bytes(2, "little"))
                    u += 1
        f.write(b'\00\00')

    @staticmethod
    def __convert_colours(data, width: int, height: int):
        pixels = [0] * width * height
        if len(data) % 2 != 0:
            sys.exit('wrong number of data for color converter')
        u = 0

        #each pixel is stored on 2 bytes, in A1 R5 G5 B5  format
        pixels_data = memoryview(data).cast('H')
        for pixel in pixels_data:
            # 5 bits means 2^5-1 = 31
            red =  round((pixel >> 10 &   31) * (255/31))
            green = round((pixel >> 5 &  31) * (255/31))
            blue = round( (pixel &  31) * (255/31))
            alpha = round((pixel >15 & 1) * 255)
            
            pixels[u] = (red, green, blue, alpha)
            u += 1
        return pixels
'''
class C:
    def __init__(self):
        self._x = None

    @property
    def x(self):
        """I'm the 'x' property."""
        return self._x

    @x.setter
    def x(self, value):
        self._x = value

    @x.deleter
    def x(self):
        del self._x
'''
